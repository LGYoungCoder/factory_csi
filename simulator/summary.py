"""Signal_Summary computed only from observable factory.db data."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def signal_summary(dataset_id: str, db_path: Path) -> str:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        lines = [f"dataset {dataset_id}: {n} products"]
        q = (
            "SELECT tester_id, model_id, COUNT(*), SUM(result='FAIL') FROM eol_tests "
            "WHERE is_retest=0 AND origin='historical' GROUP BY tester_id, model_id ORDER BY tester_id, model_id"
        )
        per: dict[str, list[tuple[str, int, int]]] = {}
        for tester, model, cnt, fails in conn.execute(q):
            per.setdefault(tester, []).append((model, cnt, fails))
        for tester, items in per.items():
            tot, fl = sum(c for _, c, _ in items), sum(f for _, _, f in items)
            parts = ", ".join(f"{m} {100 * f / c:.2f}% ({f}/{c})" for m, c, f in items)
            lines.append(f"  {tester}: FAIL_Rate {100 * fl / tot:.2f}% ({fl}/{tot}) | {parts}")
        for tester in ("EOL-A", "EOL-B"):
            row = conn.execute(
                "SELECT MIN(deviation), MAX(deviation), COUNT(*) FROM reference_sample_checks "
                "WHERE tester_id=? AND origin='historical'", (tester,)
            ).fetchone()
            if row[2]:
                lines.append(f"  {tester} reference deviation: {row[0]:+.4f} .. {row[1]:+.4f} V ({row[2]} checks)")
            else:
                lines.append(f"  {tester} reference deviation: no reference sample checks")
        pc = conn.execute("SELECT COUNT(*) FROM process_changes").fetchone()[0]
        lines.append(f"  process changes: {pc}")
        return "\n".join(lines)
    finally:
        conn.close()
