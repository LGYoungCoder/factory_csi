# Development Log

Real entries only, appended at the end of each phase.

## 2026-11-15 – Phase 1: Specs and repository foundation
- Wrote 7 Kiro specs (`.kiro/specs/*`) in Requirements-First order: the requirements first, then one shared `docs/architecture.md` with short per-spec `design.md` pointers and lean `tasks.md`. We stopped refining requirements in depth once they reached about 3,000 lines and switched to coding.
- A cross-spec consistency pass fixed several conflicts: the event catalog, decision payload, budget (LLM calls 25 → 40), dashboard data path (through MCP only), and scenario signal strength. We checked the last one against the downstream detector windows.
- Foundation: uv project with 4 import-linter contracts, Makefile, `.env.example` (LiteLLM provider examples), MIT license, Vite/React/TS/Tailwind scaffold.
- Kiro hooks were created with Kiro's hook tool: python-tests-on-save, frontend-typecheck-on-save, secret-guard. The secret guard caught a fake `sk-…` key in a probe file during its self-test.
- Issue: PyPI timed out from the dev machine. We installed with `UV_DEFAULT_INDEX` set to the Tsinghua mirror via an env var only, so the mirror is not baked into config.
- Issue: TypeScript 6 deprecates `baseUrl`. We removed it; `paths` works without it.

## 2026-11-15 – Phase 2: Virtual factory simulator
- Implemented `factory_data` (schema with CHECK/FK constraints, ids, timeutil, physics with the no-flip rule, world state, batch Append_Function) and `simulator` (generator with scenario parameter sets, ground truth, atomic writers, content hash, registry, reset, CLI).
- The statistical acceptance criteria from the spec became the reusable checks in `tests/unit/simulator/checks.py`. `scripts/find_seeds.py` scans seeds against them: 60 seeds give 93%/68%/70%/37% pass rates for ds-00..03. Scenario C is the most fragile (Model B routing before the window uses only ~30 products), so default seeds 1/2/3/6 are pinned in the registry.
- Test suite: 35 deterministic tests in ~5 s (reproducibility, FK integrity, route order, answer-key leak scan, reset keeps ground truth and never imports it, append atomicity, CLI errors).
- Decision: tester bias in world state is stored in normalized units (fraction of model tolerance half-width), not volts, so one drift parameter applies to both models. Reference tolerance is stored in volts.

## 2026-11-15 – Phase 3: Industrial MCP Server
- The installed MCP Python SDK is 2.3.0. In v2, `FastMCP` was renamed to `mcp.server.mcpserver.MCPServer`, result fields are snake_case (`is_error`, `structured_content`), and the in-memory `mcp.Client(server)` exists. We probed the API with a small script before writing the server.
- Tools return `CallToolResult`: success carries `structured_content`; domain errors are `is_error` results whose text is a JSON body `{error_code, message, details, call_id, dataset_id}`. Argument type errors come from SDK validation as plain-text errors, and the backend client maps them to INVALID_ARGUMENT.
- Verification engine (the only world-state reader): simulated clock `data end + 10 min × k`, noise seeded by SHA-256(seed, k, type, target), no-flip rule, batch append in one transaction, idempotency ledger under `logs/mcp/verifications/` with a file lock. A ledger entry stops applying once its created rows disappear (dataset reset).
- 11 integration tests (~7 s): real stdio transport, SQL parity of `get_eol_summary`, structured errors, verification outcomes against ground truth for ds-01/02/03, idempotency, reproducibility after reset, and an audit-hook test proving `ground_truth.json` is never opened and `world_state.json` is read only during verification.
- Bug found by the tests: ds-02's affected set (all P-2.4 products) includes passing products. The retest test now picks failed affected SNs.

## 2026-11-15 – Phase 4/5: Investigation engine, verification loop, API
- Probed LiteLLM 1.109 + DeepSeek before writing the LLM layer: JSON mode, tool calling and `thinking={"type":"disabled"}` all work. A JSON call takes about 1 s; `completion_cost` reports cost.
- Probed LangGraph 1.2 `interrupt()` / `Command(resume=…)` with `AsyncSqliteSaver` in a 3-node script before building the real graph.
- Implemented: deterministic analytics (MSA first: reference-sample trend and gaps, historical retests, tester comparison, model stratification, mix shift, process change KS/MWU, before/after FAIL_Rate, material lots, events), the evidence registry in app.db (idempotent by finding key), guardrails (HIGH requires verification evidence; no valid citations → INSUFFICIENT; banned phrases), an 11-node StateGraph, the proposal validator, judgment diff, the conclusion rule, a 10-section report, and a FastAPI layer with SSE, decisions, retry, restart recovery and dashboards served only through MCP.
- Bugs found in the first real runs:
  - Pydantic request models defined inside `create_app()` were treated as query params, so we moved them to module level.
  - The LangGraph node wrapper was a sync lambda returning a coroutine (`InvalidUpdateError`), so we replaced it with an async factory.
  - DeepSeek wrote a 900+ character conclusion, which hit the schema limit, and the case went to FAILED_LLM. This exercised the retry path: after a server restart, `POST /retry` resumed at `finalize_conclusion` from the checkpoint and completed. Fix: text limits are generous and the prompt gives word guidance; list limits truncate instead of failing.
- Real runs (auto-approve rank 1, about 60–90 s and about $0.012–0.016 per case with deepseek-flash):
  - ds-01: TESTER_MEASUREMENT_DRIFT rose to HIGH after the cross retest (5/5 PASS on EOL-A).
  - ds-02: PROCESS_PARAMETER_DEVIATION rose to HIGH after the ST-20 config audit (MISMATCH).
  - ds-03: final INSUFFICIENT_EVIDENCE (MIX and PROCESS tied at MEDIUM; EOL-B reference UNAVAILABLE).
- Tests: 19 deterministic backend/API tests (~7 s) plus 4 `llm` tests on the real DeepSeek API (A, B, C with reject_all, immediate conclude), all passing in 4.5 min.

## 2026-11-16 – Phase 6: Investigation workspace UI
- React 19 + TS + Tailwind v4 + Radix primitives (shadcn style) + ECharts + TanStack Query + react-markdown (rehype-slug + rehype-sanitize).
- Live state: the case snapshot from REST is the source of truth. A pure SSE reducer tracks progress, warnings and audit, and triggers debounced snapshot refetches. The SSE client reconnects with backoff and resumes from the last seq.
- ESLint (React 19 hook rules) caught two real issues: `setState` inside an effect (fixed by keying `DecisionPanel` on the proposal round) and a ref written during render in the SSE hook.
- Verified with headless Chrome screenshots against the live backend (`docs/screenshots/`): workspace after a completed Scenario A case, the Next Best Verification panel while awaiting approval, and the report view. Headless Chrome with `--virtual-time-budget` hangs while an SSE stream is open, so screenshots of running cases use `--timeout`.
- 8 Vitest tests (reducer, formatting, status mapping, decision panel validation, LLM-unavailable disabling). tsc and ESLint are clean.

## 2026-11-16 – Phase 7: Delivery
- Docker:
  - Backend image (python 3.11-slim + uv, non-root, entrypoint generates missing datasets) and frontend image (node build → nginx with `proxy_buffering off` for SSE). Compose binds both services to 127.0.0.1.
  - Docker Hub dropped connections from the dev machine, so base images and package indexes are now build args/env vars. The images were built through public mirrors.
  - `docker compose up` was verified end to end: health check, LLM OK, SPA routes, SSE through nginx (123 events replayed), and a full Scenario A investigation through port 8080 (COMPLETED, Tester drift MEDIUM→HIGH).
- Evaluation harness (`python -m evaluation`) runs in-process with an isolated `var/eval/` and is scored against the ground truth.
  - The first eval run hung after the first case. The SSE stream only closed when `completed` was the last event, but the engine emits `node_completed` after `completed`.
  - Fix: close once a `completed` was seen and the case is terminal. The API test now reproduces the real event order.
- LiteLLM fetched a remote price map at import (TLS EOF behind the dev network, about 10 s delay). It is now pinned to the bundled map with `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- Added README, KIRO_USAGE.md, demo script, Devpost draft, `make check-submission` (18 checks, all PASS), clean-clone script and an optional GitHub Actions workflow.

## 2026-11-16 – Evaluation-driven fixes
- First full `make eval` (3 runs per scenario): A 3/3, B 3/3 and C 2/3 acceptable. In the failing C run the LLM put PROCESS_PARAMETER_DEVIATION at MEDIUM using only the FAIL_Rate increase as support.
  - Fix (code, not prompt-only): every finding and verification now carries `data.mechanism` tags. Examples: a reference check out of tolerance or a retest PASS on the other tester → tester drift; a recorded program change with a KS-significant parameter shift → process deviation; within-model tester parity plus a mix shift → product mix shift.
  - Guardrail: a hypothesis can reach MEDIUM or higher only if some supporting evidence shows its mechanism. The tags are shown to the LLM in the evidence digest.
- The report check flagged "No single root cause is established" (pattern "root cause is") and "not a proven root cause". Both are hedges, not overclaims, so a negation-aware `overclaims()` replaces the raw regex in validation, tests and evaluation.
- Added the metric "verification evidence cited by the final hypotheses" next to "verification that changed a support level". The latter is low when a verification confirms an already HIGH hypothesis, which is expected.
- Final `make eval` (deepseek-flash, 9 runs): all completed; anomaly detection, conclusion acceptability and report completeness 9/9; citation validity 1.0; proposal legality 1.0; verification outcomes match ground truth 1.0; about 55–85 s and about US$0.011–0.013 per case. Scenario C concludes "suspected product mix shift, MEDIUM", which the answer key allows (≤ MEDIUM).
- Docker backend rebuilt with these fixes; stack healthy on :8080.
