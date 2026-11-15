"""Dev helper: report which seeds satisfy every statistical criterion per scenario.

Usage: uv run python scripts/find_seeds.py [--start 1] [--count 200]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulator.generator import GenerationError, generate  # noqa: E402
from simulator.registry import list_entries  # noqa: E402
from simulator.scenarios import scenario_for_key  # noqa: E402
from tests.unit.simulator.checks import CHECKS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--datasets", default="ds-00,ds-01,ds-02,ds-03")
    args = ap.parse_args()
    for e in list_entries():
        if e.dataset_id not in args.datasets.split(","):
            continue
        ok, fails = [], {}
        for seed in range(args.start, args.start + args.count):
            try:
                ds = generate(scenario_for_key(e.scenario_key), seed)
            except GenerationError as exc:
                fails[str(exc)[:60]] = fails.get(str(exc)[:60], 0) + 1
                continue
            problems = CHECKS[e.dataset_id](ds.rows)
            if problems:
                for p in problems:
                    key = p.split(":")[0][:60]
                    fails[key] = fails.get(key, 0) + 1
            else:
                ok.append(seed)
        print(f"{e.dataset_id}: {len(ok)}/{args.count} seeds pass; first: {ok[:10]}")
        for k, v in sorted(fails.items(), key=lambda kv: -kv[1])[:6]:
            print(f"    {v:4d} x {k}")


if __name__ == "__main__":
    main()
