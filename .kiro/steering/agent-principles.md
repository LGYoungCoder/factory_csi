---
inclusion: fileMatch
fileMatchPattern: ["backend/agent/**", "backend/llm/**", "backend/evidence/**"]
---
# Agent design principles

- Statistics are computed by deterministic Python (`backend.analytics`). The LLM interprets the results and never computes rates or invents data.
- Evidence items (`EV-001`…) are created only by code, with template summaries and record_refs that resolve via `get_source_records`. Every LLM claim cites Evidence IDs; unknown IDs → repair, then drop + `citation_dropped`.
- Support levels are evidence support (HIGH/MEDIUM/LOW/INSUFFICIENT), never probabilities. HIGH requires at least one supporting verification evidence item. Without valid supporting citations the level is INSUFFICIENT.
- Mechanism rule: MEDIUM or HIGH requires at least one supporting evidence item tagged with the hypothesis category in `data.mechanism` (set by analytics/verification code). A FAIL_Rate increase alone shows no mechanism → LOW.
- Banned overclaiming phrases (checked by `overclaims()`, negated hedges such as "not a proven cause" are allowed): "confirmed root cause", "the root cause is", "root cause has been identified", "proven", "definitely", "certainly caused".
- Every simulated verification needs an explicit human `approve` decision. Only `execute_verification` calls `run_simulated_verification`.
- Budgets are enforced in code: 20 MCP calls, 40 LLM calls, 3 verification rounds, 2 reject_all per case.
- LLM failures set the case to FAILED_LLM (resumable). Never substitute text.
- The LLM context gets compact evidence digests only: no raw measurement arrays, no scenario labels, no world state, no ground truth.
