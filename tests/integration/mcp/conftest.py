from __future__ import annotations

from pathlib import Path

import pytest

from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.registry import list_entries
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Fresh copy of all four datasets per test (verification appends rows)."""
    out = tmp_path / "data"
    for e in list_entries():
        write_dataset(out, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    return out
