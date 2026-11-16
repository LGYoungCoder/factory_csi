# How Kiro was used to build Factory CSI

This file lists only what actually happened. The chronological record is in [docs/dev-log.md](docs/dev-log.md).

## Features used

| Kiro feature | Where | What it did for the project |
|---|---|---|
| Agent chat (Autopilot) | whole project | Planning, the spec workflow, implementation, running tests and fixing failures in one session |
| Specs (Requirements-First) | `.kiro/specs/` (7 specs) | The product brief became 144 EARS requirements across the simulator, MCP server, engine, verification loop, API, UI and delivery |
| Steering | `.kiro/steering/` (7 files) | Persistent rules: no fallback text, ground-truth isolation, citation and support rules, test markers, the PyPI mirror note |
| Hooks | `.kiro/hooks/` (3, created with Kiro's hook tool) | Tests and ruff on Python save, tsc and eslint on frontend save, secret guard on every save |
| MCP | `.kiro/settings/mcp.json` | The project's own Industrial MCP Server registered (ds-00..ds-03) for Kiro's agent; `run_simulated_verification` is never auto-approved |

## Specs: decomposing the work

1. The original brief (Chinese, very long) was clarified first: LLM provider, no fallback mode, local-only deployment, docs in English.
2. One spec per module was written Requirements-First. A dedicated cross-spec consistency pass found real conflicts:
   - three different event-name lists;
   - decision note rules that differed between the API and verification-loop specs;
   - an LLM budget of 25 calls that would allow only one verification round in the worst case (raised to 40);
   - scenario C parameters whose signal was too weak for the downstream detector to fire. We calculated this before any code existed and strengthened the parameters.
3. At about 3,000 lines of requirements we decided the detail was enough for a hackathon. Design became one shared `docs/architecture.md` with short per-spec `design.md` pointers, and each `tasks.md` holds 4–7 coarse tasks (checked off as modules were completed).
4. Acceptance criteria were used directly as tests. For example, every statistical criterion of the simulator spec is a check in `tests/unit/simulator/checks.py`, and `scripts/find_seeds.py` uses the same checks to pick dataset seeds that satisfy all of them.

## Hooks: improving testing

- `python-tests-on-save` maps the saved path to the related test directory (`simulator/**` → `tests/unit/simulator/`, `industrial_mcp/**` → `tests/integration/mcp/`, …). It runs ruff and `pytest -m "not llm"`, so saving never costs LLM money.
  - Its self-test showed that pytest exit code 5 ("no tests collected") was reported as a failure, which we fixed.
  - The hook writes its full log to `logs/hooks/` and prints a one-line summary, because PostFileSave output may not be shown.
- `secret-guard` scans every saved file for key patterns and masks all but the last 4 characters.
  - It caught a synthetic `sk-…` key in its own self-test.
  - `secret_guard.sh --all` runs over all tracked files before every commit; every commit in this repo was preceded by a clean scan.
- `frontend-typecheck-on-save` runs tsc and eslint. ESLint's React 19 hook rules caught two real bugs (setState inside an effect, a ref written during render).

## MCP: developing and integrating the server

- The MCP Python SDK installed was 2.3.0, where `FastMCP` became `MCPServer` and result fields became snake_case. A small probe script checked tool results, error results and argument validation before the server was written.
- The server is tested over real stdio subprocesses and the in-memory client. An audit-hook test proves `ground_truth.json` is never opened.
- The same server code serves two paths:
  - Runtime: the FastAPI backend keeps one stdio session per dataset and serves the dashboards through it.
  - Development: `.kiro/settings/mcp.json` registers it for Kiro's agent.

## Observed effect

- Real failures found by tests and real runs and fixed in the same session:
  - LangGraph node wrapper returned a coroutine;
  - FastAPI body models defined in a closure were treated as query params;
  - LLM output exceeded a schema limit, which exercised the FAILED_LLM → retry-from-checkpoint path;
  - ds-02 test selection included passing products.
- The working build covers the simulator, MCP server, agent, API, UI, Docker and evaluation. It has 66 deterministic tests, 11 frontend tests and 4 real-LLM tests, all passing at the time of writing.
