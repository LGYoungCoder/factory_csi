"""Identifier formats. Formats are mutually exclusive across types.

| type      | historical     | verification   |
|-----------|----------------|----------------|
| order_id  | PO-123456      | –              |
| sn        | SN-1234567     | –              |
| step_id   | PS-12345678    | –              |
| meas_id   | PM-12345678    | PM-V1234567    |
| event_id  | EQE-123456     | –              |
| change_id | PC-12345       | –              |
| test_id   | T-123456       | T-V12345       |
| check_id  | RC-12345       | RC-V1234       |
"""

from __future__ import annotations

import re

_FORMATS: dict[str, tuple[str, int, str | None, int | None]] = {
    # type: (prefix, digits, verification prefix, verification digits)
    "order_id": ("PO-", 6, None, None),
    "sn": ("SN-", 7, None, None),
    "step_id": ("PS-", 8, None, None),
    "meas_id": ("PM-", 8, "PM-V", 7),
    "event_id": ("EQE-", 6, None, None),
    "change_id": ("PC-", 5, None, None),
    "test_id": ("T-", 6, "T-V", 5),
    "check_id": ("RC-", 5, "RC-V", 4),
}

ID_TYPES = tuple(_FORMATS)


def _regex(id_type: str) -> re.Pattern[str]:
    prefix, digits, vprefix, vdigits = _FORMATS[id_type]
    alts = [re.escape(prefix) + rf"\d{{{digits}}}"]
    if vprefix:
        alts.append(re.escape(vprefix) + rf"\d{{{vdigits}}}")
    return re.compile("^(?:" + "|".join(alts) + ")$")


_REGEX = {t: _regex(t) for t in _FORMATS}


def _check_type(id_type: str) -> None:
    if id_type not in _FORMATS:
        raise ValueError(f"unknown identifier type {id_type!r}; known types: {', '.join(ID_TYPES)}")


def is_valid(id_type: str, value: object) -> bool:
    _check_type(id_type)
    return isinstance(value, str) and len(value) <= 32 and bool(_REGEX[id_type].match(value))


def make_id(id_type: str, number: int) -> str:
    _check_type(id_type)
    prefix, digits, _, _ = _FORMATS[id_type]
    if not 0 < number < 10**digits:
        raise ValueError(f"{id_type} number {number} out of range")
    return f"{prefix}{number:0{digits}d}"


def make_verification_id(id_type: str, number: int) -> str:
    _check_type(id_type)
    _, _, vprefix, vdigits = _FORMATS[id_type]
    if vprefix is None or vdigits is None:
        raise ValueError(f"{id_type} has no verification-origin format")
    if not 0 < number < 10**vdigits:
        raise ValueError(f"{id_type} verification number {number} out of range")
    return f"{vprefix}{number:0{vdigits}d}"


def verification_number(id_type: str, value: str) -> int | None:
    """Return N for a verification id like ``T-V00012`` or None for historical ids."""
    _, _, vprefix, _ = _FORMATS[id_type]
    if vprefix and value.startswith(vprefix):
        return int(value[len(vprefix):])
    return None


def is_verification_id(id_type: str, value: str) -> bool:
    return is_valid(id_type, value) and verification_number(id_type, value) is not None
