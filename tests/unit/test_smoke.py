import importlib

import pytest


@pytest.mark.parametrize(
    "name", ["factory_data", "simulator", "industrial_mcp", "backend", "evaluation"]
)
def test_top_level_packages_import(name: str) -> None:
    assert importlib.import_module(name) is not None
