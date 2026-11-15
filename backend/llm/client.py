"""LLM access through LiteLLM. One code path for every provider; switching = editing .env."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # use bundled price map, no network fetch at import

import litellm  # noqa: E402

from backend.settings import Settings  # noqa: E402
from factory_data.timeutil import format_ts

litellm.suppress_debug_info = True
litellm.drop_params = True  # ignore provider-unsupported options such as `thinking`

_KEY_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|Bearer\s+\S+)")


def redact(text: str, secret: str = "") -> str:
    out = _KEY_RE.sub("[redacted]", text or "")
    if secret:
        out = out.replace(secret, "[redacted]")
    return out


class LLMUnavailableError(RuntimeError):
    """LLM could not produce a completion. Never answered with substitute text."""


class LLMMisconfiguredError(LLMUnavailableError):
    pass


class BudgetExhaustedError(RuntimeError):
    def __init__(self, budget: str, limit: int, used: int):
        super().__init__(f"{budget} budget exhausted ({used}/{limit})")
        self.budget, self.limit, self.used = budget, limit, used


@dataclass
class CaseRuntime:
    """Per-case counters and sinks shared by every node (not checkpointed; counters reloaded from the store)."""

    case_id: str
    dataset_id: str
    max_mcp: int
    max_llm: int
    mcp_used: int = 0
    llm_used: int = 0
    emit: Callable[[str, dict], Awaitable[None]] | None = None
    record_llm: Callable[[dict], Awaitable[None]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def remaining_llm(self) -> int:
        return self.max_llm - self.llm_used

    def remaining_mcp(self) -> int:
        return self.max_mcp - self.mcp_used


class LLMClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def model(self) -> str:
        return self.s.effective_model

    def _kwargs(self) -> dict:
        kw: dict[str, Any] = {"model": self.model, "timeout": self.s.llm_timeout_s, "num_retries": 0}
        key = self.s.llm_api_key.get_secret_value()
        if key:
            kw["api_key"] = key
        if self.s.llm_base_url:
            kw["api_base"] = self.s.llm_base_url
        if self.model.startswith("deepseek/"):
            kw["thinking"] = {"type": "enabled" if self.s.llm_thinking else "disabled"}
        return kw

    async def raw_completion(self, messages: list[dict], **extra: Any) -> Any:
        """One completion with transport retries (counts as one LLM call). Raises LLMUnavailableError."""
        key = self.s.llm_api_key.get_secret_value()
        last: Exception | None = None
        for attempt in range(self.s.llm_max_retries + 1):
            try:
                return await litellm.acompletion(messages=messages, **self._kwargs(), **extra)
            except (litellm.AuthenticationError, litellm.NotFoundError, litellm.PermissionDeniedError) as exc:
                raise LLMMisconfiguredError(redact(str(exc), key)[:300]) from exc
            except litellm.BadRequestError as exc:
                raise LLMUnavailableError(redact(str(exc), key)[:300]) from exc
            except Exception as exc:  # noqa: BLE001 – timeouts, 5xx, 429, connection errors
                last = exc
                if attempt < self.s.llm_max_retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMUnavailableError(redact(f"{type(last).__name__}: {last}", key)[:300])

    async def complete(self, rt: CaseRuntime | None, purpose: str, messages: list[dict], **extra: Any) -> Any:
        """Budgeted, recorded completion for a case."""
        if rt is not None and rt.llm_used >= rt.max_llm:
            raise BudgetExhaustedError("llm_calls", rt.max_llm, rt.llm_used)
        if rt is not None:
            rt.llm_used += 1
        t0 = time.perf_counter()
        status, resp, err = "ok", None, None
        try:
            resp = await self.raw_completion(messages, **extra)
            return resp
        except LLMUnavailableError as exc:
            status, err = type(exc).__name__, str(exc)
            raise
        finally:
            latency = round((time.perf_counter() - t0) * 1000, 1)
            usage = getattr(resp, "usage", None)
            try:
                cost = float(litellm.completion_cost(completion_response=resp)) if resp is not None else None
            except Exception:  # noqa: BLE001
                cost = None
            text = ""
            if resp is not None:
                msg = resp.choices[0].message
                text = msg.content or json.dumps([tc.model_dump() for tc in (msg.tool_calls or [])], default=str)
            cap = self.s.llm_audit_text_max_chars
            rec = {
                "case_id": rt.case_id if rt else None, "purpose": purpose, "model": self.model,
                "tokens_in": getattr(usage, "prompt_tokens", None), "tokens_out": getattr(usage, "completion_tokens", None),
                "latency_ms": latency, "status": status, "cost_usd": cost,
                "prompt": redact(json.dumps(messages, default=str))[:cap], "response": (text or err or "")[:cap],
            }
            if rt is not None and rt.record_llm:
                await rt.record_llm(rec)
            if rt is not None and rt.emit:
                await rt.emit("llm_call", {k: rec[k] for k in ("purpose", "model", "tokens_in", "tokens_out",
                                                               "latency_ms", "status")})


@dataclass
class HealthResult:
    status: str  # OK | UNAVAILABLE | MISCONFIGURED
    model: str
    provider: str
    checked_at: str | None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "model": self.model, "provider": self.provider,
                "checked_at": self.checked_at, "reason": self.reason}


class HealthChecker:
    def __init__(self, client: LLMClient):
        self.client = client
        self.result = HealthResult("UNAVAILABLE", client.model, client.model.split("/")[0], None, "not yet checked")
        self._lock = asyncio.Lock()

    def _age_s(self) -> float:
        if not self.result.checked_at:
            return float("inf")
        from factory_data.timeutil import parse_ts

        return (datetime.now(UTC) - parse_ts(self.result.checked_at)).total_seconds()

    async def check(self) -> HealthResult:
        async with self._lock:
            s = self.client.s
            provider = self.client.model.split("/")[0]
            now = format_ts(datetime.now(UTC))
            if not s.llm_api_key.get_secret_value() and provider != "ollama":
                self.result = HealthResult("MISCONFIGURED", self.client.model, provider, now, "LLM_API_KEY is empty")
                return self.result
            try:
                await self.client.raw_completion([{"role": "user", "content": "Reply with the single word OK."}],
                                                 max_tokens=5)
                self.result = HealthResult("OK", self.client.model, provider, now)
            except LLMMisconfiguredError as exc:
                self.result = HealthResult("MISCONFIGURED", self.client.model, provider, now, str(exc)[:200])
            except LLMUnavailableError as exc:
                self.result = HealthResult("UNAVAILABLE", self.client.model, provider, now, str(exc)[:200])
            return self.result

    async def ensure_fresh(self, max_age_s: float = 60) -> HealthResult:
        if self._age_s() > max_age_s:
            return await self.check()
        return self.result

    def mark_unavailable(self, reason: str) -> None:
        r = self.result
        self.result = HealthResult("UNAVAILABLE", r.model, r.provider, format_ts(datetime.now(UTC)), reason[:200])
