from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from factory_data import ids
from factory_data.db import make_engine
from factory_data.enums import SupportLevel
from factory_data.schema import metadata, stations
from factory_data.timeutil import format_ts, parse_ts
from factory_data.world_state import ReferenceSample
from factory_data.world_state import TesterBias as Bias

aware = st.datetimes(
    min_value=datetime(1000, 1, 2), max_value=datetime(9999, 12, 30), timezones=st.just(UTC)
).map(lambda d: d.replace(microsecond=0))


@given(aware)
def test_timeutil_round_trip(dt: datetime) -> None:
    assert parse_ts(format_ts(dt)) == dt
    assert format_ts(parse_ts(format_ts(dt))) == format_ts(dt)


def test_timeutil_conversion_and_errors() -> None:
    assert format_ts(datetime(2026, 11, 2, 15, 8, tzinfo=timezone(timedelta(hours=5)))) == "2026-11-02T10:08:00Z"
    assert format_ts(datetime(2026, 11, 2, 10, 8, 0, 999999, tzinfo=UTC)) == "2026-11-02T10:08:00Z"
    with pytest.raises(ValueError, match="timezone-aware"):
        format_ts(datetime(2026, 11, 2))
    for bad in ["2026-11-02T10:08:00+00:00", "2026-11-02T10:08:00z", "2026-11-02T10:08:00", "2026-13-01T00:00:00Z",
                "2026-02-30T00:00:00Z", "2026-11-02T24:00:00Z", " 2026-11-02T10:08:00Z", "2026-11-02", 123,
                "2026-11-02T10:08:00.5Z"]:
        with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM:SSZ"):
            parse_ts(bad)


@given(st.sampled_from(ids.ID_TYPES), st.integers(min_value=1, max_value=99999))
def test_generated_ids_validate_and_are_exclusive(id_type: str, n: int) -> None:
    value = ids.make_id(id_type, n)
    assert ids.is_valid(id_type, value)
    assert all(not ids.is_valid(other, value) for other in ids.ID_TYPES if other != id_type)


def test_id_validation_edge_cases() -> None:
    assert not ids.is_valid("sn", "")
    assert not ids.is_valid("sn", " SN-2600001")
    assert not ids.is_valid("sn", 2600001)
    assert ids.is_valid("test_id", ids.make_verification_id("test_id", 1))
    assert ids.make_verification_id("check_id", 3) == "RC-V0003"
    with pytest.raises(ValueError, match="unknown identifier type"):
        ids.is_valid("nope", "x")


def test_support_level_order() -> None:
    assert SupportLevel.LOW < SupportLevel.MEDIUM < SupportLevel.HIGH
    assert SupportLevel("HIGH") >= SupportLevel.MEDIUM


def test_schema_check_and_fk_constraints(tmp_path) -> None:  # noqa: ANN001
    from factory_data.schema import eol_tests, equipment

    eng = make_engine(tmp_path / "f.db")
    metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(insert(stations).values(station_id="EOL", name="x", sequence=1))
        c.execute(insert(equipment).values(equipment_id="EOL-A", station_id="EOL", name="x", equipment_type="t"))
    with pytest.raises(IntegrityError), eng.begin() as c:
        c.execute(insert(equipment).values(equipment_id="X", station_id="NOPE", name="x", equipment_type="t"))
    with pytest.raises(IntegrityError), eng.begin() as c:
        c.execute(insert(eol_tests).values(test_id="T-000001", sn="SN-0000001", tester_id="EOL-A",
                                           ts="2026-11-02T06:00:00Z", model_id="M", result="MAYBE",
                                           is_retest=False, origin="historical"))
    eng.dispose()


def test_bias_and_reference_rules() -> None:
    b = Bias(base=0.0, onset="2026-11-02T09:00:00Z", slope_per_hour=0.2)
    assert b.at("2026-11-02T08:59:59Z") == 0.0
    assert b.at("2026-11-02T11:00:00Z") == pytest.approx(0.4)
    with pytest.raises(ValueError):
        ReferenceSample(availability="UNAVAILABLE", tolerance=0.1, sample_id="s", test_item="t", nominal=1,
                        half_width=1)
