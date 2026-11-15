"""SQLAlchemy Core schema of factory.db (12 tables)."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

_RESULT = "('PASS','FAIL')"
_ORIGIN = "('historical','verification')"

stations = Table(
    "stations",
    metadata,
    Column("station_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("sequence", Integer, nullable=False),
)

equipment = Table(
    "equipment",
    metadata,
    Column("equipment_id", String, primary_key=True),
    Column("station_id", String, ForeignKey("stations.station_id"), nullable=False),
    Column("name", String, nullable=False),
    Column("equipment_type", String, nullable=False),
)

product_models = Table(
    "product_models",
    metadata,
    Column("model_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("ov_lower", Float, nullable=False),
    Column("ov_upper", Float, nullable=False),
    CheckConstraint("ov_lower < ov_upper", name="ck_model_limits"),
)

production_orders = Table(
    "production_orders",
    metadata,
    Column("order_id", String, primary_key=True),
    Column("model_id", String, ForeignKey("product_models.model_id"), nullable=False),
    Column("qty", Integer, nullable=False),
    Column("start_ts", String, nullable=False),
)

products = Table(
    "products",
    metadata,
    Column("sn", String, primary_key=True),
    Column("order_id", String, ForeignKey("production_orders.order_id"), nullable=False),
    Column("model_id", String, ForeignKey("product_models.model_id"), nullable=False),
    Column("material_lot", String, nullable=False),
    Column("created_ts", String, nullable=False),
)

process_steps = Table(
    "process_steps",
    metadata,
    Column("step_id", String, primary_key=True),
    Column("sn", String, ForeignKey("products.sn"), nullable=False),
    Column("station_id", String, ForeignKey("stations.station_id"), nullable=False),
    Column("equipment_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("start_ts", String, nullable=False),
    Column("end_ts", String, nullable=False),
    Column("recipe_version", String, nullable=False),
    Column("result", String, nullable=False),
    CheckConstraint(f"result IN {_RESULT}", name="ck_step_result"),
)

process_measurements = Table(
    "process_measurements",
    metadata,
    Column("meas_id", String, primary_key=True),
    Column("step_id", String, ForeignKey("process_steps.step_id"), nullable=False),
    Column("sn", String, ForeignKey("products.sn"), nullable=False),
    Column("equipment_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("ts", String, nullable=False),
    Column("parameter", String, nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String, nullable=False),
    Column("program_version", String, nullable=False),
    CheckConstraint("parameter IN ('torque','angle')", name="ck_meas_parameter"),
)

equipment_events = Table(
    "equipment_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("equipment_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("ts", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("details_json", Text, nullable=False),
    CheckConstraint(
        "event_type IN ('state','alarm','maintenance','calibration')", name="ck_event_type"
    ),
)

process_changes = Table(
    "process_changes",
    metadata,
    Column("change_id", String, primary_key=True),
    Column("equipment_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("ts", String, nullable=False),
    Column("change_type", String, nullable=False),
    Column("old_value", String, nullable=False),
    Column("new_value", String, nullable=False),
    Column("changed_by", String, nullable=False),
)

eol_tests = Table(
    "eol_tests",
    metadata,
    Column("test_id", String, primary_key=True),
    Column("sn", String, ForeignKey("products.sn"), nullable=False),
    Column("tester_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("ts", String, nullable=False),
    Column("model_id", String, ForeignKey("product_models.model_id"), nullable=False),
    Column("result", String, nullable=False),
    Column("failure_code", String, nullable=True),
    Column("is_retest", Boolean, nullable=False),
    Column("retest_of", String, ForeignKey("eol_tests.test_id"), nullable=True),
    Column("origin", String, nullable=False),
    CheckConstraint(f"result IN {_RESULT}", name="ck_test_result"),
    CheckConstraint(f"origin IN {_ORIGIN}", name="ck_test_origin"),
)

eol_measurements = Table(
    "eol_measurements",
    metadata,
    Column("meas_id", String, primary_key=True),
    Column("test_id", String, ForeignKey("eol_tests.test_id"), nullable=False),
    Column("test_item", String, nullable=False),
    Column("value", Float, nullable=False),
    Column("lower_limit", Float, nullable=False),
    Column("upper_limit", Float, nullable=False),
    Column("result", String, nullable=False),
    CheckConstraint(f"result IN {_RESULT}", name="ck_eolmeas_result"),
)

reference_sample_checks = Table(
    "reference_sample_checks",
    metadata,
    Column("check_id", String, primary_key=True),
    Column("tester_id", String, ForeignKey("equipment.equipment_id"), nullable=False),
    Column("ts", String, nullable=False),
    Column("sample_id", String, nullable=False),
    Column("test_item", String, nullable=False),
    Column("nominal", Float, nullable=False),
    Column("measured", Float, nullable=False),
    Column("deviation", Float, nullable=False),
    Column("result", String, nullable=False),
    Column("origin", String, nullable=False),
    CheckConstraint(f"result IN {_RESULT}", name="ck_ref_result"),
    CheckConstraint(f"origin IN {_ORIGIN}", name="ck_ref_origin"),
)

#: insertion / hashing order (parents before children)
TABLE_ORDER: tuple[Table, ...] = (
    stations,
    equipment,
    product_models,
    production_orders,
    products,
    process_steps,
    process_measurements,
    equipment_events,
    process_changes,
    eol_tests,
    eol_measurements,
    reference_sample_checks,
)
TABLES: dict[str, Table] = {t.name: t for t in TABLE_ORDER}

TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "production_orders": ("start_ts",),
    "products": ("created_ts",),
    "process_steps": ("start_ts", "end_ts"),
    "process_measurements": ("ts",),
    "equipment_events": ("ts",),
    "process_changes": ("ts",),
    "eol_tests": ("ts",),
    "reference_sample_checks": ("ts",),
}


def primary_key(table_name: str) -> str:
    return TABLES[table_name].primary_key.columns.values()[0].name
