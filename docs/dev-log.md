# Development Log

Real entries only, appended at the end of each phase.

## 2026-11-15 – Phase 1: Specs and repository foundation
- Wrote 7 Kiro specs (`.kiro/specs/*`) in Requirements-First order: the requirements first, then one shared `docs/architecture.md` with short per-spec `design.md` pointers and lean `tasks.md`. We stopped refining requirements in depth once they reached about 3,000 lines and switched to coding.
- A cross-spec consistency pass fixed several conflicts: the event catalog, decision payload, budget (LLM calls 25 → 40), dashboard data path (through MCP only), and scenario signal strength. We checked the last one against the downstream detector windows.
- Foundation: uv project with 4 import-linter contracts, Makefile, `.env.example` (LiteLLM provider examples), MIT license, Vite/React/TS/Tailwind scaffold.
- Kiro hooks were created with Kiro's hook tool: python-tests-on-save, frontend-typecheck-on-save, secret-guard. The secret guard caught a fake `sk-…` key in a probe file during its self-test.
- Issue: PyPI timed out from the dev machine. We installed with `UV_DEFAULT_INDEX` set to the Tsinghua mirror via an env var only, so the mirror is not baked into config.
- Issue: TypeScript 6 deprecates `baseUrl`. We removed it; `paths` works without it.
