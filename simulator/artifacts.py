"""Write observable artifacts (factory.db, world_state.json) atomically. No ground-truth code here."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import insert

from factory_data.db import make_engine
from factory_data.schema import TABLE_ORDER, metadata
from simulator.generator import GeneratedDataset, Rows

FACTORY_DB = "factory.db"
WORLD_STATE = "world_state.json"
SIDE_CARS = ("-journal", "-wal", "-shm")


def write_factory_db(path: Path, rows: Rows) -> None:
    engine = make_engine(path)
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            for table in TABLE_ORDER:
                data = rows[table.name]
                if data:
                    conn.execute(insert(table), data)
    finally:
        engine.dispose()


def remove_sidecars(db_path: Path) -> None:
    for suffix in SIDE_CARS:
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()


def write_observable_artifacts(directory: Path, ds: GeneratedDataset) -> None:
    """Replace factory.db and world_state.json in ``directory`` via temp file + rename."""
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    tmp_db = directory / f".tmp-{token}-{FACTORY_DB}"
    tmp_ws = directory / f".tmp-{token}-{WORLD_STATE}"
    try:
        write_factory_db(tmp_db, ds.rows)
        tmp_ws.write_text(ds.world_state.to_json(), encoding="utf-8")
        remove_sidecars(directory / FACTORY_DB)
        os.replace(tmp_db, directory / FACTORY_DB)
        os.replace(tmp_ws, directory / WORLD_STATE)
    finally:
        for p in (tmp_db, tmp_ws):
            if p.exists():
                p.unlink()
            remove_sidecars(p)
