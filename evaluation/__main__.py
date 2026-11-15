"""``python -m evaluation --runs 3 --datasets ds-01,ds-02,ds-03``"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluation.harness import markdown, run, summarize


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--datasets", default="ds-01,ds-02,ds-03")
    ap.add_argument("--workdir", type=Path, default=Path("var/eval"))
    ap.add_argument("--out", type=Path, default=Path("evaluation/results"))
    ap.add_argument("--doc", type=Path, default=Path("docs/evaluation.md"))
    a = ap.parse_args()
    if a.runs < 1:
        print("error: --runs must be ≥ 1", file=sys.stderr)
        return 2
    try:
        res = run([d.strip() for d in a.datasets.split(",") if d.strip()], a.runs, a.workdir,
                  log=lambda m: print(m, flush=True))
    except SystemExit as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = summarize(res)
    a.out.mkdir(parents=True, exist_ok=True)
    stamp = res["generated_at"].replace("-", "").replace(":", "")
    (a.out / f"{stamp}.json").write_text(json.dumps(res, indent=1))
    (a.out / "latest-summary.json").write_text(json.dumps({"generated_at": res["generated_at"], "model": res["model"],
                                                          "runs": res["runs"], "summary": summary}, indent=1))
    a.doc.write_text(markdown(res, summary))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
