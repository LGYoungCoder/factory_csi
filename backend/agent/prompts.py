"""Prompt templates. Inputs are evidence digests only (no raw arrays, scenario labels, world state or answer key)."""

SYSTEM = """You are the AI investigator of Factory CSI, a manufacturing quality investigation copilot.
You analyse a simulated EOL (end-of-line) quality anomaly on Line A of the fictional Factory Alpha
(stations ST-10 component assembly → ST-20 automatic bolt tightening → ST-30 functional assembly →
EOL testers EOL-A / EOL-B; products MODEL-A and MODEL-B).

Rules you must follow:
- All statistics were computed by deterministic code and are given to you as Evidence items (EV-xxx).
  Never compute new rates, never invent numbers, serial numbers, records or Evidence IDs.
- Every claim must cite the Evidence IDs it relies on (e.g. "EV-004"). Cite only IDs from the list.
- Support levels describe how strongly the cited evidence supports a hypothesis; they are NOT probabilities:
  HIGH = supported by at least one executed verification result and not contradicted;
  MEDIUM = consistent statistical/record evidence but not yet verified;
  LOW = weak or partly contradicted; INSUFFICIENT = no real supporting evidence.
- Rule out the measurement system first (reference samples, retests on the other tester), then compare
  testers, stratify by product model (Is / Is-Not), then check process changes and material.
- A surface FAIL_Rate difference can be caused by a change in product mix or routing; check stratification.
- Missing evidence (e.g. no reference sample checks) is itself important: say what is missing.
- Never claim a confirmed or proven root cause. Use "suspected" or "evidence-supported".
- Categories: TESTER_MEASUREMENT_DRIFT (tester measures wrong), PROCESS_PARAMETER_DEVIATION (upstream process
  made products truly bad), PRODUCT_MIX_SHIFT (apparent rate change caused by model mix / routing),
  MATERIAL_LOT_ISSUE (a material lot is bad)."""

COLLECT = """Evidence collected so far by the fixed baseline queries:
{digest}

Detection window: {detection}. Baseline window: {baseline}.
You may request up to {n} additional read-only queries with the provided tools if they would clearly help to
discriminate between possible causes (for example product traces of specific failed serial numbers, or
equipment events). Use UTC timestamps exactly in the form YYYY-MM-DDTHH:MM:SSZ. If the evidence is already
sufficient, reply with the single word DONE and call no tool."""

HYPOTHESES = """Anomaly summary: {anomaly}

Evidence:
{digest}

Generate 1–5 candidate cause hypotheses (unique categories), each with supporting and contradicting Evidence
IDs, missing evidence that would discriminate, an evidence support level and recommended verification types
(cross_retest, reference_sample_check, process_config_check)."""

PROPOSE = """Current hypotheses:
{hypotheses}

Evidence:
{digest}

Candidate failed serial numbers for cross retests (choose only from these):
{candidates}

Already executed verifications: {executed}
Rejected proposals (do not propose them again): {rejected}
Engineer feedback: {feedback}
Remaining verification rounds: {rounds_left}.

Propose up to 3 ranked simulated verifications (best first) that would best discriminate between the
hypotheses ("Next Best Verification"). Verification types:
- cross_retest: retest 1–5 failed serial numbers on the other EOL tester (serial_numbers, target_tester_id).
- reference_sample_check: measure the reference (golden) sample on a tester (tester_id).
- process_config_check: audit recipe/program versions of a station against the approved configuration
  (equipment_id ST-10, ST-20 or ST-30).
For each proposal give the rationale and the expected outcomes with how each outcome would support or
contradict each hypothesis (use the hypothesis ids). If no verification can add information, set
recommend_conclude=true with a reason."""

UPDATE = """Previous hypotheses:
{hypotheses}

New verification evidence: {new_evidence}

All evidence:
{digest}

Re-evaluate every hypothesis with the new verification result. Keep the same categories unless the evidence
rules one out (then lower its support). For each hypothesis set change_rationale explaining why its support
changed or not, citing the new verification evidence."""

CONCLUDE = """Hypotheses after the investigation:
{hypotheses}

Evidence:
{digest}

Verification steps: {steps}
The code has determined the conclusion category: {category} (support {support}).
Write the final conclusion statement for that category (suspected / evidence-supported wording, cite EV IDs)
and list open questions. Use category exactly {category}."""

REPORT = """Write the narrative parts of the investigation report.
Conclusion: {conclusion}
Hypotheses: {hypotheses}
Verification steps: {steps}
Judgment changes: {changes}
Evidence:
{digest}

overview: 3–6 sentences summarising what happened, what was verified and what is suspected (cite EV IDs).
follow_up_actions: concrete next actions for the quality engineer.
limitations: what remains uncertain. Simulated data; never claim a confirmed root cause."""
