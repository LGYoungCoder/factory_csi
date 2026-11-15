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
