"""Append_Function: add verification-origin rows to factory.db in one transaction."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from factory_data import ids
from factory_data.enums import Origin, TestResult
from factory_data.schema import eol_measurements, eol_tests, products, reference_sample_checks
from factory_data.timeutil import is_ts

EOL_TESTERS = ("EOL-A", "EOL-B")
MAX_TESTS_PER_BATCH = 5


class AppendError(ValueError):
    def __init__(self, field_name: str, message: str, position: int | None = None):
        self.field_name = field_name
        self.position = position
        where = f" (record {position})" if position is not None else ""
        super().__init__(f"{field_name}{where}: {message}")


@dataclass(frozen=True)
class MeasurementInput:
    test_item: str
    value: float
    lower_limit: float
    upper_limit: float
    result: TestResult


@dataclass(frozen=True)
class EolTestInput:
    sn: str
    tester_id: str
    ts: str
    model_id: str
    result: TestResult
    failure_code: str | None
    is_retest: bool
    retest_of: str | None
    measurements: list[MeasurementInput] = field(default_factory=list)


@dataclass(frozen=True)
class RefCheckInput:
    tester_id: str
    ts: str
    sample_id: str
    test_item: str
    nominal: float
    measured: float
    result: TestResult


@dataclass
class AppendResult:
    test_ids: list[str] = field(default_factory=list)
    meas_ids: list[str] = field(default_factory=list)
    check_ids: list[str] = field(default_factory=list)

    @property
    def refs(self) -> list[str]:
        return (
            [f"eol_tests:{t}" for t in self.test_ids]
            + [f"eol_measurements:{m}" for m in self.meas_ids]
            + [f"reference_sample_checks:{c}" for c in self.check_ids]
        )


def _next_number(conn, table, column, id_type: str) -> int:  # noqa: ANN001
    vals = conn.execute(select(column).where(column.like("%-V%"))).scalars().all()
    nums = [ids.verification_number(id_type, v) or 0 for v in vals]
    return (max(nums) if nums else 0) + 1


def append_verification_records(
    engine: Engine,
    eol_tests_in: list[EolTestInput] | None = None,
    ref_checks_in: list[RefCheckInput] | None = None,
) -> AppendResult:
    """Validate and insert a batch (≤5 EOL tests + reference checks) atomically."""
    tests_in = list(eol_tests_in or [])
    checks_in = list(ref_checks_in or [])
    if not tests_in and not checks_in:
        raise AppendError("batch", "empty batch")
    if len(tests_in) > MAX_TESTS_PER_BATCH:
        raise AppendError("eol_tests", f"at most {MAX_TESTS_PER_BATCH} EOL tests per batch")
    result = AppendResult()
    with engine.begin() as conn:
        for i, t in enumerate(tests_in):
            if t.tester_id not in EOL_TESTERS:
                raise AppendError("tester_id", f"must be one of {EOL_TESTERS}", i)
            if not is_ts(t.ts):
                raise AppendError("ts", "not a UTC timestamp YYYY-MM-DDTHH:MM:SSZ", i)
            if not t.measurements:
                raise AppendError("measurements", "at least one measurement required", i)
            row = conn.execute(select(products.c.model_id).where(products.c.sn == t.sn)).first()
            if row is not None and row.model_id != t.model_id:
                raise AppendError("model_id", "differs from the model of the SN", i)
            if t.is_retest:
                if not t.retest_of:
                    raise AppendError("retest_of", "required when is_retest is true", i)
                orig = conn.execute(select(eol_tests.c.sn).where(eol_tests.c.test_id == t.retest_of)).first()
                if orig is not None and orig.sn != t.sn:
                    raise AppendError("retest_of", "references a test of a different SN", i)
            elif t.retest_of:
                raise AppendError("retest_of", "must be empty when is_retest is false", i)
        for i, c in enumerate(checks_in):
            if c.tester_id not in EOL_TESTERS:
                raise AppendError("tester_id", f"must be one of {EOL_TESTERS}", len(tests_in) + i)
            if not is_ts(c.ts):
                raise AppendError("ts", "not a UTC timestamp", len(tests_in) + i)

        tnum = _next_number(conn, eol_tests, eol_tests.c.test_id, "test_id")
        mnum = _next_number(conn, eol_measurements, eol_measurements.c.meas_id, "meas_id")
        cnum = _next_number(conn, reference_sample_checks, reference_sample_checks.c.check_id, "check_id")
        try:
            for t in tests_in:
                test_id = ids.make_verification_id("test_id", tnum)
                tnum += 1
                conn.execute(
                    insert(eol_tests).values(
                        test_id=test_id, sn=t.sn, tester_id=t.tester_id, ts=t.ts, model_id=t.model_id,
                        result=str(t.result), failure_code=t.failure_code, is_retest=t.is_retest,
                        retest_of=t.retest_of, origin=Origin.VERIFICATION.value,
                    )
                )
                result.test_ids.append(test_id)
                for m in t.measurements:
                    meas_id = ids.make_verification_id("meas_id", mnum)
                    mnum += 1
                    conn.execute(
                        insert(eol_measurements).values(
                            meas_id=meas_id, test_id=test_id, test_item=m.test_item, value=m.value,
                            lower_limit=m.lower_limit, upper_limit=m.upper_limit, result=str(m.result),
                        )
                    )
                    result.meas_ids.append(meas_id)
            for c in checks_in:
                check_id = ids.make_verification_id("check_id", cnum)
                cnum += 1
                conn.execute(
                    insert(reference_sample_checks).values(
                        check_id=check_id, tester_id=c.tester_id, ts=c.ts, sample_id=c.sample_id,
                        test_item=c.test_item, nominal=c.nominal, measured=c.measured,
                        deviation=round(c.measured - c.nominal, 4), result=str(c.result),
                        origin=Origin.VERIFICATION.value,
                    )
                )
                result.check_ids.append(check_id)
        except IntegrityError as exc:
            raise AppendError("foreign_key", f"insert rejected: {exc.orig}") from exc
    return result


def count_verification_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        a = conn.execute(
            select(func.count()).select_from(eol_tests).where(eol_tests.c.origin == Origin.VERIFICATION.value)
        ).scalar_one()
        b = conn.execute(
            select(func.count())
            .select_from(reference_sample_checks)
            .where(reference_sample_checks.c.origin == Origin.VERIFICATION.value)
        ).scalar_one()
    return int(a + b)
