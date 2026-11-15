"""Dev helper: run one investigation through the HTTP API, auto-approving the rank-1 proposal.

Usage: uv run python scripts/drive_case.py ds-01 [--base http://127.0.0.1:8000] [--reset]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=120)
    if a.reset:
        print("reset", c.post(f"/api/datasets/{a.dataset}/reset").json().get("epoch"))
    r = c.post("/api/cases", json={"dataset_id": a.dataset})
    if r.status_code != 201:
        print(r.status_code, r.text)
        return 1
    case_id = r.json()["case_id"]
    print("case", case_id)
    t0, seen = time.time(), 0
    while time.time() - t0 < a.timeout:
        d = c.get(f"/api/cases/{case_id}").json()
        evs = c.get(f"/api/cases/{case_id}/events", params={"after": seen}, timeout=5,
                    headers={"Accept": "text/event-stream"}) if False else None
        _ = evs
        if d["status"] == "AWAITING_APPROVAL" and d["pending"]:
            props = d["pending"]["proposals"]
            for p in props:
                print(f"  proposal {p['proposal_id']} {p['verification_type']} {p['params']} :: {p['rationale'][:140]}")
            if props:
                body = {"action": "approve", "proposal_id": props[0]["proposal_id"]}
            else:
                body = {"action": "conclude"}
            print("  decision", body, c.post(f"/api/cases/{case_id}/decision", json=body).status_code)
        elif d["status"] in ("COMPLETED", "FAILED", "FAILED_LLM"):
            break
        time.sleep(2)
    d = c.get(f"/api/cases/{case_id}").json()
    print("status", d["status"], d.get("error"))
    print("budgets", json.dumps(d["budgets"]))
    print("llm usage", d["llm_usage"])
    for h in d["hypotheses"]:
        print(f"  {h['hypothesis_id']} {h['category']} {h['support']} sup={h['supporting_evidence']}")
    for j in d["judgment_changes"]:
        print(f"  change r{j.get('round')} {j['category']} {j['before']}->{j['after']} {j['direction']} {j['because']}")
    print("conclusion", json.dumps(d["conclusion"])[:600])
    print("elapsed", round(time.time() - t0, 1), "s")
    return 0 if d["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
