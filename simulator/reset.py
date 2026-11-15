"""Reset_Function: restore factory.db and world_state.json of a dataset. Never touches ground truth."""

from __future__ import annotations

from pathlib import Path

from simulator.artifacts import write_observable_artifacts
from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.registry import get_entry
from simulator.scenarios import scenario_for_key


class ResetError(RuntimeError):
    pass


def reset_dataset(dataset_id: str, data_dir: str | Path) -> Path:
    entry = get_entry(dataset_id)  # raises before touching any file
    target = Path(data_dir) / dataset_id
    try:
        ds = generate(scenario_for_key(entry.scenario_key), entry.default_seed, DEFAULT_CONFIG)
        write_observable_artifacts(target, ds)
    except Exception as exc:  # noqa: BLE001
        raise ResetError(f"reset of {dataset_id} failed: {exc}") from exc
    return target
