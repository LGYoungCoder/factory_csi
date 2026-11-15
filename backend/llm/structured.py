"""Structured output: JSON mode + Pydantic schema in the prompt + validation with ≤2 repair attempts."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.llm.client import CaseRuntime, LLMClient

T = TypeVar("T", bound=BaseModel)
MAX_REPAIRS = 2


class StructuredOutputError(RuntimeError):
    def __init__(self, purpose: str, attempts: int, errors: list[str]):
        super().__init__(f"{purpose}: no valid structured output after {attempts} attempts: {'; '.join(errors)[:500]}")
        self.attempts, self.errors = attempts, errors


def schema_prompt(model: type[BaseModel]) -> str:
    return (
        "Respond with ONE JSON object only (no markdown, no prose) that validates against this JSON Schema:\n"
        + json.dumps(model.model_json_schema(), separators=(",", ":"))
    )


async def structured_call(
    llm: LLMClient,
    rt: CaseRuntime,
    purpose: str,
    system: str,
    user: str,
    model: type[T],
    check: Callable[[T], list[str]] | None = None,
    sanitize: Callable[[T], T] | None = None,
) -> T:
    """Return a validated object. ``check`` returns semantic errors (e.g. unknown citations) that trigger a
    repair; if they persist after the last attempt, ``sanitize`` removes the offending items."""
    messages = [{"role": "system", "content": system + "\n\n" + schema_prompt(model)},
                {"role": "user", "content": user}]
    errors: list[str] = []
    last_obj: T | None = None
    for attempt in range(1 + MAX_REPAIRS):
        resp = await llm.complete(rt, purpose if attempt == 0 else f"{purpose}:repair{attempt}", messages,
                                  response_format={"type": "json_object"})
        text = resp.choices[0].message.content or ""
        try:
            obj = model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            errors = [str(exc)[:1500]]
            last_obj = None
        else:
            last_obj = obj
            errors = check(obj) if check else []
            if not errors:
                return obj
        if attempt < MAX_REPAIRS:
            messages += [{"role": "assistant", "content": text[:6000]},
                         {"role": "user", "content": "Your JSON was rejected. Fix these problems and answer with the "
                                                     "complete corrected JSON object only:\n- " + "\n- ".join(errors)}]
    if last_obj is not None and sanitize is not None:
        return sanitize(last_obj)
    raise StructuredOutputError(purpose, 1 + MAX_REPAIRS, errors)
