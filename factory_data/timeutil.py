"""The single UTC timestamp utility: ``YYYY-MM-DDTHH:MM:SSZ``."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

EXPECTED_FORM = "YYYY-MM-DDTHH:MM:SSZ"
_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def format_ts(dt: datetime) -> str:
    """Format a timezone-aware datetime as a UTC timestamp, truncating fractional seconds."""
    if not isinstance(dt, datetime):
        raise ValueError(f"expected a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("a timezone-aware datetime is required (got a naive datetime)")
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: object) -> datetime:
    """Parse a UTC timestamp string into an aware UTC datetime."""
    if not isinstance(value, str) or not _PATTERN.match(value):
        raise ValueError(f"invalid UTC timestamp {value!r}; expected form {EXPECTED_FORM}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"invalid UTC timestamp {value!r}; expected form {EXPECTED_FORM}") from exc


def is_ts(value: object) -> bool:
    try:
        parse_ts(value)
    except ValueError:
        return False
    return True


def add_seconds(ts: str, seconds: float) -> str:
    return format_ts(parse_ts(ts) + timedelta(seconds=seconds))


def hours_between(start: str, end: str) -> float:
    return (parse_ts(end) - parse_ts(start)).total_seconds() / 3600.0
