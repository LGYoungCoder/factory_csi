"""Shared server context, structured errors, validation helpers and call logging."""

from __future__ import annotations

import itertools
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from factory_data import ids
from factory_data.timeutil import format_ts, parse_ts

ERROR_CODES = ("INVALID_ARGUMENT", "NOT_FOUND", "UNAVAILABLE", "LIMIT_EXCEEDED", "INTERNAL")
EOL_TESTERS = ("EOL-A", "EOL-B")
STATION_EQUIPMENT = ("ST-10", "ST-20", "ST-30")
ALL_EQUIPMENT = STATION_EQUIPMENT + EOL_TESTERS
MAX_BUCKETS = 200


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        assert code in ERROR_CODES
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def invalid(field_name: str, message: str) -> ToolFailure:
    return ToolFailure("INVALID_ARGUMENT", f"{field_name}: {message}", {"field": field_name})


@dataclass
class ServerContext:
    dataset_id: str
    data_dir: Path
    log_dir: Path
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    @property
    def dataset_path(self) -> Path:
        return self.data_dir / self.dataset_id

    @property
    def db_path(self) -> Path:
        return self.dataset_path / "factory.db"

    @property
    def world_state_path(self) -> Path:
        return self.dataset_path / "world_state.json"

    def next_call_id(self) -> str:
        return f"MCP-{next(self._seq):06d}"

    def connect(self, *, read_only: bool = True) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise ToolFailure("UNAVAILABLE", f"dataset {self.dataset_id} is not available; run `make seed`")
        mode = "ro" if read_only else "rw"
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode={mode}", uri=True, timeout=10)
        except sqlite3.Error as exc:
            raise ToolFailure("UNAVAILABLE", f"dataset {self.dataset_id} could not be opened") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def log(self, entry: dict) -> None:
        try:
            d = self.log_dir / "mcp"
            d.mkdir(parents=True, exist_ok=True)
            with (d / f"{self.dataset_id}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError:
            pass  # logging must never break a tool call

    def run(self, tool: str, fn: Callable[..., dict], args: dict[str, Any]) -> tuple[dict, bool]:
        """Execute a tool body; returns (body, is_error). Every call is logged."""
        call_id = self.next_call_id()
        t0 = time.perf_counter()
        is_error = False
        try:
            data = fn(self, **args)
            body = {"call_id": call_id, "dataset_id": self.dataset_id, **data}
            code = None
        except ToolFailure as exc:
            is_error = True
            code = exc.code
            body = {"error_code": exc.code, "message": exc.message, "details": exc.details,
                    "call_id": call_id, "dataset_id": self.dataset_id}
        except Exception:  # noqa: BLE001
            is_error = True
            code = "INTERNAL"
            body = {"error_code": "INTERNAL", "message": f"internal error in {tool}", "details": {},
                    "call_id": call_id, "dataset_id": self.dataset_id}
        text = json.dumps(body, sort_keys=True)
        self.log({
            "call_id": call_id, "tool": tool, "arguments": json.dumps(args, sort_keys=True, default=str)[:4096],
            "status": "error" if is_error else "ok", "error_code": code,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            "ts": format_ts(_now()), "result_size": len(text),
        })
        return body, is_error


def _now():  # noqa: ANN202
    from datetime import UTC, datetime

    return datetime.now(UTC)


# --- validation -----------------------------------------------------------------------
def parse_window(start: str, end: str) -> tuple[str, str]:
    try:
        s, e = parse_ts(start), parse_ts(end)
    except ValueError as exc:
        raise invalid("start/end", str(exc)) from exc
    if s >= e:
        raise invalid("start/end", "start must be earlier than end")
    return start, end


def check_bucket(bucket_minutes: int, start: str, end: str) -> int:
    if not isinstance(bucket_minutes, int) or not 15 <= bucket_minutes <= 240:
        raise invalid("bucket_minutes", "must be an integer from 15 to 240")
    n = buckets_count(start, end, bucket_minutes)
    if n > MAX_BUCKETS:
        raise ToolFailure("LIMIT_EXCEEDED", f"window yields {n} buckets (max {MAX_BUCKETS})",
                          {"field": "bucket_minutes", "received": n, "maximum": MAX_BUCKETS})
    return bucket_minutes


def buckets_count(start: str, end: str, minutes: int) -> int:
    span = (parse_ts(end) - parse_ts(start)).total_seconds()
    return int(-(-span // (minutes * 60)))


def bucket_edges(start: str, end: str, minutes: int) -> list[tuple[str, str]]:
    s, e = parse_ts(start), parse_ts(end)
    out, cur = [], s
    while cur < e:
        nxt = min(cur + timedelta(minutes=minutes), e)
        out.append((format_ts(cur), format_ts(nxt)))
        cur = nxt
    return out


def bucket_index(ts: str, start: str, minutes: int) -> int:
    return int((parse_ts(ts) - parse_ts(start)).total_seconds() // (minutes * 60))


def check_tester(value: str, field_name: str = "tester_id") -> str:
    if value not in EOL_TESTERS:
        raise invalid(field_name, f"must be one of {list(EOL_TESTERS)}")
    return value


def check_equipment(conn: sqlite3.Connection, value: str, field_name: str = "equipment_id") -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or any(c.isspace() for c in value):
        raise invalid(field_name, "must be a non-empty identifier without whitespace")
    if conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (value,)).fetchone() is None:
        raise ToolFailure("NOT_FOUND", f"equipment {value!r} not found", {"field": field_name})
    return value


def check_sn_list(values: list[str], maximum: int, *, allow_duplicates: bool = True) -> list[str]:
    if not isinstance(values, list) or not values:
        raise invalid("serial_numbers", "at least one serial number required")
    if len(values) > maximum:
        raise ToolFailure("LIMIT_EXCEEDED", f"serial_numbers has {len(values)} entries (max {maximum})",
                          {"field": "serial_numbers", "received": len(values), "maximum": maximum})
    for v in values:
        if not ids.is_valid("sn", v):
            raise invalid("serial_numbers", f"{v!r} is not a serial number (SN-1234567)")
    if not allow_duplicates and len(set(values)) != len(values):
        raise invalid("serial_numbers", "duplicate serial numbers")
    return list(dict.fromkeys(values))


def r4(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def r3(x: float | None) -> float | None:
    return None if x is None else round(float(x), 3)


def rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
