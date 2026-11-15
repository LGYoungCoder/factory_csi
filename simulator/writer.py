"""Full dataset writer: factory.db + world_state.json + ground_truth.json, swapped in atomically."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from simulator.artifacts import FACTORY_DB, WORLD_STATE, write_factory_db
from simulator.generator import GeneratedDataset
from simulator.ground_truth import build_ground_truth

GROUND_TRUTH = "ground_truth.json"


def write_dataset(out_dir: Path, ds: GeneratedDataset) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / ds.dataset_id
    token = uuid.uuid4().hex[:8]
    tmp = out_dir / f".tmp-{ds.dataset_id}-{token}"
    old = out_dir / f".old-{ds.dataset_id}-{token}"
    try:
        tmp.mkdir()
        write_factory_db(tmp / FACTORY_DB, ds.rows)
        (tmp / WORLD_STATE).write_text(ds.world_state.to_json(), encoding="utf-8")
        (tmp / GROUND_TRUTH).write_text(build_ground_truth(ds).to_json(), encoding="utf-8")
        if target.exists():
            os.replace(target, old)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
    return target
