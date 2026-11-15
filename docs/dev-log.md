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
