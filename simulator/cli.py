"""``python -m simulator generate|seed`` – the only orchestration that writes ground truth."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simulator.config import DEFAULT_CONFIG
from simulator.generator import MAX_SEED, generate
from simulator.registry import get_entry_by_key, list_entries
from simulator.scenarios import SCENARIOS, scenario_for_key
from simulator.summary import signal_summary
from simulator.writer import write_dataset


def _seed(value: str) -> int:
    try:
        seed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--seed must be an integer, got {value!r}") from exc
    if not 0 <= seed <= MAX_SEED:
        raise argparse.ArgumentTypeError(f"--seed must be within 0..{MAX_SEED}")
    return seed


def _generate_one(key: str, seed: int | None, out: Path) -> None:
    entry = get_entry_by_key(key)
    ds = generate(scenario_for_key(key), entry.default_seed if seed is None else seed, DEFAULT_CONFIG)
    target = write_dataset(out, ds)
    print(signal_summary(ds.dataset_id, target / "factory.db"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate one dataset")
    g.add_argument("--scenario", required=True, choices=list(SCENARIOS))
    g.add_argument("--seed", type=_seed, default=None, help="default: registry seed")
    g.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("seed", help="generate ds-00..ds-03 with registry seeds")
    s.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        out: Path = args.out
        out.mkdir(parents=True, exist_ok=True)
        if not out.is_dir():
            raise OSError(f"output directory {out} is not writable")
        if args.cmd == "generate":
            _generate_one(args.scenario, args.seed, out)
        else:
            for e in list_entries():
                _generate_one(e.scenario_key, None, out)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
