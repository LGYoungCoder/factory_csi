"""MCP Client Manager: one long-lived stdio session per dataset to the Industrial MCP Server."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_RETRY_EXCLUDED = {"run_simulated_verification"}


class MCPToolError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None, call_id: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details, self.call_id = code, message, details or {}, call_id


class _Session:
    def __init__(self, params: StdioServerParameters):
        self.params = params
        self.session: ClientSession | None = None
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.error: str | None = None
        self.lock = asyncio.Lock()
        self.status = "STARTING"

    async def _main(self) -> None:
        try:
            async with stdio_client(self.params, errlog=sys.stderr) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                self.session = s
                self.status = "READY"
                self.ready.set()
                await self.stop.wait()
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"[:300]
            self.status = "FAILED"
        finally:
            self.session = None
            if self.status != "FAILED":
                self.status = "STOPPED"
            self.ready.set()

    async def start(self, timeout: float = 20) -> None:
        self.ready.clear()
        self.stop.clear()
        self.status = "STARTING"
        self.task = asyncio.create_task(self._main())
        with suppress(TimeoutError):
            await asyncio.wait_for(self.ready.wait(), timeout)
        if self.session is None:
            self.status = "FAILED"
            raise MCPToolError("UNAVAILABLE", f"MCP session could not start: {self.error or 'timeout'}")

    async def close(self) -> None:
        self.stop.set()
        if self.task:
            with suppress(Exception):
                await asyncio.wait_for(self.task, 5)


class MCPClientManager:
    def __init__(self, data_dir: Path, log_dir: Path, recorder: Callable[[dict], Awaitable[None]] | None = None,
                 timeout_s: float = 30.0):
        self.data_dir, self.log_dir = data_dir.resolve(), log_dir.resolve()
        self.recorder = recorder
        self.timeout_s = timeout_s
        self._sessions: dict[str, _Session] = {}

    def available(self, dataset_id: str) -> bool:
        return (self.data_dir / dataset_id / "factory.db").is_file()

    def status(self) -> dict[str, str]:
        return {k: v.status for k, v in self._sessions.items()}

    def _params(self, dataset_id: str) -> StdioServerParameters:
        return StdioServerParameters(command=sys.executable, args=[
            "-m", "industrial_mcp", "--dataset", dataset_id, "--data-dir", str(self.data_dir),
            "--log-dir", str(self.log_dir)])

    async def _get(self, dataset_id: str, restart: bool = False) -> _Session:
        if not self.available(dataset_id):
            raise MCPToolError("UNAVAILABLE", f"dataset {dataset_id} is not available")
        s = self._sessions.get(dataset_id)
        if s is not None and restart:
            await s.close()
            s = None
        if s is None or s.session is None:
            s = _Session(self._params(dataset_id))
            self._sessions[dataset_id] = s
            await s.start()
        return s

    async def list_tools(self, dataset_id: str) -> list[Any]:
        s = await self._get(dataset_id)
        assert s.session is not None
        return (await s.session.list_tools()).tools

    async def call(self, dataset_id: str, tool: str, args: dict, case_id: str | None = None) -> dict:
        attempts = 1 if tool in READ_RETRY_EXCLUDED else 2
        for attempt in range(attempts):
            s = await self._get(dataset_id, restart=attempt > 0)
            t0 = time.perf_counter()
            status, code, body, call_id = "OK", None, None, None
            try:
                async with s.lock:
                    assert s.session is not None
                    res = await s.session.call_tool(tool, args, read_timeout_seconds=self.timeout_s)
                text = res.content[0].text if res.content else ""
                if res.is_error:
                    try:
                        err = json.loads(text)
                    except json.JSONDecodeError:
                        err = {"error_code": "INVALID_ARGUMENT", "message": text[:300]}
                    status, code, call_id = "TOOL_ERROR", err.get("error_code", "INTERNAL"), err.get("call_id")
                    raise MCPToolError(code, err.get("message", ""), err.get("details"), call_id)
                body = res.structured_content or json.loads(text)
                call_id = body.get("call_id")
                return body
            except MCPToolError:
                raise
            except Exception as exc:  # noqa: BLE001 – transport failure / timeout
                status, code = ("TIMEOUT" if isinstance(exc, TimeoutError) else "TRANSPORT_ERROR"), "UNAVAILABLE"
                s.status = "FAILED"
                if attempt + 1 >= attempts:
                    raise MCPToolError("UNAVAILABLE", f"MCP call {tool} failed: {type(exc).__name__}") from exc
            finally:
                if self.recorder:
                    await self.recorder({
                        "case_id": case_id, "dataset_id": dataset_id, "tool": tool,
                        "arguments": json.dumps(args, sort_keys=True)[:4000], "status": status, "error_code": code,
                        "duration_ms": round((time.perf_counter() - t0) * 1000, 1), "mcp_call_id": call_id,
                        "result_size": len(json.dumps(body)) if body else None,
                        "result_summary": None,
                    })
        raise MCPToolError("UNAVAILABLE", f"MCP call {tool} failed")

    async def restart(self, dataset_id: str) -> None:
        if dataset_id in self._sessions:
            await self._get(dataset_id, restart=True)

    async def close(self) -> None:
        for s in list(self._sessions.values()):
            await s.close()
        self._sessions.clear()
