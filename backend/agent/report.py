"""Investigation report: sections 2–8 deterministic from state; narrative parts written by the LLM."""

from __future__ import annotations

import re

from backend.analytics.findings import timeline
from backend.analytics.stats import fmt_p, pct

DISCLAIMER = ("All data and verification results are simulated (fictional Factory Alpha). This report is decision "
              "support only; it does not state a certified root cause and no real equipment was touched.")
SECTIONS = ["Anomaly overview", "Anomaly metrics", "Timeline", "Key evidence", "Candidate causes",
            "Verification steps executed", "Impact of new evidence on judgment", "Suspected affected product scope",
            "Recommended follow-up actions", "Open questions and limitations"]


def _scope(st: dict, evidence: list[dict]) -> dict:
    concl = (st.get("conclusion") or {}).get("category")
    anomalies = st.get("anomaly", {}).get("anomalies", [])
    by_key = {e.get("data", {}).get("equipment_id"): e for e in evidence if e["title"].endswith("elevated in the last 3 h")}
    if concl == "PROCESS_PARAMETER_DEVIATION":
        e = next((x for x in evidence if x["title"].startswith("FAIL_Rate before vs after")), None)
        if e:
            rows = e["data"]["by_tester"]
            n = sum(r["after"]["fail_count"] for r in rows)
            return {"basis": "first-test failures after the process change (all EOL testers)", "count": n,
                    "serial_numbers": [r["sn"] for r in e["data"].get("ref_rows", []) if r.get("sn")][:20],
                    "evidence": [e["id"]]}
    sns, total, ev_ids = [], 0, []
    for a in anomalies:
        e = by_key.get(a["equipment_id"])
        total += a["window_counts"][0]
        if e:
            ev_ids.append(e["id"])
            sns += [r["sn"] for r in e["data"].get("ref_rows", [])]
    basis = ("first-test failures in the detection window on " + ", ".join(a["equipment_id"] for a in anomalies)
             if anomalies else "none")
    return {"basis": basis, "count": total, "serial_numbers": sns[:20], "evidence": ev_ids}


def build_report(st: dict, evidence: list[dict], events: list[dict]) -> dict:
    anomaly = st.get("anomaly") or {}
    decisions = [e["payload"] for e in events if e["type"] == "decision_recorded"]
    initial = (st.get("history") or [{}])[0].get("hypotheses", []) if st.get("history") else []
    return {
        "case_id": st.get("case_id"),
        "dataset_id": st.get("dataset_id"),
        "short_form": anomaly.get("status") != "ANOMALY",
        "anomaly": anomaly,
        "conclusion": st.get("conclusion"),
        "timeline": timeline(evidence),
        "evidence": [{k: e[k] for k in ("id", "kind", "source_system", "title", "summary", "record_refs")}
                     for e in evidence],
        "hypotheses": st.get("hypotheses", []),
        "initial_hypotheses": initial,
        "verifications": st.get("executed", []),
        "decisions": decisions,
        "judgment_changes": st.get("judgment", []),
        "scope": _scope(st, evidence),
        "budget_exhausted": st.get("budget_exhausted"),
        "disclaimer": DISCLAIMER,
        "sections": SECTIONS,
    }


EV = re.compile(r"\bEV-\d{3,}\b")


def _link(text: str | None) -> str:
    return EV.sub(lambda m: f"[{m.group(0)}](#{m.group(0).lower()})", text or "")


def render_markdown(r: dict) -> str:
    out: list[str] = [f"# Investigation Report – {r['case_id']}", "",
                      f"Dataset `{r['dataset_id']}` · Factory Alpha, Line A · **Simulation**", "",
                      f"> {r['disclaimer']}", ""]
    n = r.get("narrative") or {}
    marker = r.get("narrative_marker")
    c = r.get("conclusion") or {}

    def sec(i: int) -> None:
        out.extend([f"## {i}. {SECTIONS[i - 1]}", ""])

    sec(1)
    if r["short_form"]:
        out.append("No statistically significant EOL anomaly was detected (detection rule: last 3 h vs first 2 h, "
                   "Fisher p < 0.01 and FAIL_Rate ≥ 2 × baseline). No investigation hypotheses were generated.")
    else:
        if c:
            out.append(f"**{c.get('label')}: `{c.get('category')}`** (evidence support {c.get('support')})")
            if c.get("statement"):
                out.extend(["", _link(c["statement"])])
            if c.get("reason"):
                out.extend(["", f"_Concluded because: {c['reason']}_"])
        out.append("")
        out.append(_link(n.get("overview")) if n else f"_{marker or 'Narrative unavailable'}_")
    out.append("")

    sec(2)
    out += ["| Tester | Baseline FAIL_Rate | Detection FAIL_Rate | Fisher p | Flagged |", "|---|---|---|---|---|"]
    for t in r["anomaly"].get("testers", []):
        fb, nb = t["baseline_counts"]
        fd, nd = t["window_counts"]
        out.append(f"| {t['equipment_id']} | {pct(t['baseline_rate'])} ({fb}/{nb}) | {pct(t['window_rate'])} "
                   f"({fd}/{nd}) | {fmt_p(t['p_value'])} | {'yes' if t['flagged'] else 'no'} |")
    w = r["anomaly"].get("detected_window") or {}
    b = r["anomaly"].get("baseline_window") or {}
    out += ["", f"Baseline window {b.get('start')} – {b.get('end')}; detection window {w.get('start')} – "
                f"{w.get('end')} (UTC).", ""]

    if not r["short_form"]:
        sec(3)
        out += ["| Time (UTC) | Source | Event | Evidence |", "|---|---|---|---|"]
        for t in r["timeline"]:
            out.append(f"| {t['ts']} | {t['source_system']} | {t['description']} | {_link(t['evidence_id'])} |")
        out.append("")

    sec(4)
    for e in r["evidence"]:
        out += [f"#### {e['id']}", "", f"**{e['title']}** · {e['kind']} · {e['source_system']}", "",
                e["summary"], ""]
        if e["record_refs"]:
            out += ["Source records: " + ", ".join(f"`{x}`" for x in e["record_refs"][:10])
                    + (f" (+{len(e['record_refs']) - 10} more)" if len(e["record_refs"]) > 10 else ""), ""]

    if not r["short_form"]:
        sec(5)
        if not r["hypotheses"]:
            out.append("_Not available: no hypotheses were generated._")
        for h in r["hypotheses"]:
            out += [f"### {h['hypothesis_id']} · {h['category']} – {h['title']}", "",
                    f"Evidence support: **{h['support']}**", "", _link(h["statement"]), "",
                    "- Supporting: " + (", ".join(_link(x) for x in h["supporting_evidence"]) or "none"),
                    "- Contradicting: " + (", ".join(_link(x) for x in h["contradicting_evidence"]) or "none"),
                    "- Missing evidence: " + ("; ".join(h["missing_evidence"]) or "none"), ""]

        sec(6)
        if not r["verifications"] and not r["decisions"]:
            out.append("No verification was executed.")
        for d in r["decisions"]:
            out.append(f"- Decision `{d.get('action')}`" + (f" on {d['proposal_id']}" if d.get("proposal_id") else "")
                       + f" by {d.get('actor', 'engineer')}" + (f" – note: {d['note']}" if d.get("note") else ""))
        for v in r["verifications"]:
            out.append(f"- **{v['proposal_id']} → {v['approval_id']}** `{v['type']}` {v['params']}: "
                       f"{v['summary']} ({_link(v['evidence_id'])})")
        out.append("")

        sec(7)
        if not r["judgment_changes"]:
            out.append("No judgment changes (no verification result was evaluated).")
        else:
            out += ["| Round | Hypothesis | Before | After | Direction | Because |", "|---|---|---|---|---|---|"]
            for j in r["judgment_changes"]:
                out.append(f"| {j.get('round', '')} | {j['hypothesis_id']} {j['category']} | {j['before'] or '–'} | "
                           f"{j['after'] or '–'} | {j['direction']} | "
                           f"{', '.join(_link(x) for x in j['because']) or '–'} |")
        out.append("")

        sec(8)
        s = r["scope"]
        out += [f"Suspected scope basis: {s['basis']}. Count: **{s['count']}**.", "",
                ("Sample serial numbers: " + ", ".join(f"`{x}`" for x in s["serial_numbers"])) if s["serial_numbers"]
                else "No serial number sample available.",
                "", "Evidence: " + (", ".join(_link(x) for x in s["evidence"]) or "–"), ""]

        sec(9)
        if n:
            out += [f"- {_link(a)}" for a in n["follow_up_actions"]]
        else:
            out.append(f"_{marker or 'Narrative unavailable'}_")
        out.append("")

    sec(10)
    for q in (c.get("open_questions") or []):
        out.append(f"- {_link(q)}")
    if n.get("limitations"):
        out += ["", _link(n["limitations"])]
    if r.get("budget_exhausted"):
        out += ["", f"_Investigation budget exhausted: {r['budget_exhausted']}._"]
    out += ["", f"_{r['disclaimer']}_", ""]
    return "\n".join(out)
