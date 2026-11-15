"""``python -m industrial_mcp --dataset ds-01 --data-dir data [--log-dir logs]`` (stdio transport)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from industrial_mcp.server import create


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m industrial_mcp")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--log-dir", default=Path("logs"), type=Path)
    args = ap.parse_args()
    if not re.fullmatch(r"ds-\d{2}", args.dataset):
        print(f"error: invalid dataset id {args.dataset!r}", file=sys.stderr)
        return 2
    if not (args.data_dir / args.dataset / "factory.db").is_file():
        print(f"error: dataset {args.dataset} not found under {args.data_dir}; run `make seed`", file=sys.stderr)
        return 2
    create(args.dataset, args.data_dir, args.log_dir).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
