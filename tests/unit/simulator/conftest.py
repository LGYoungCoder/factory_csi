from __future__ import annotations

from pathlib import Path

import pytest

from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.registry import list_entries
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """All four datasets generated once per session with registry default seeds."""
    out = tmp_path_factory.mktemp("data")
    for e in list_entries():
        write_dataset(out, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    return out
