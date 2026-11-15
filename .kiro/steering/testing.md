---
inclusion: always
---
# Testing rules

- pytest with `--strict-markers`. Tests that call a real LLM carry `@pytest.mark.llm` and live in `tests/llm/`. A bare `pytest` deselects them. Run them with `make test` or `pytest -m llm`.
- No fake or mock LLM exists in product code. LLM tests use the real provider from `.env` and fail (not skip) when the LLM status is not OK. LLM tests assert properties, never exact text.
- Deterministic tests need no network and no key: `tests/unit/` (simulator, backend logic) and `tests/integration/` (real MCP stdio subprocesses, API).
- Run tests when a module is complete (not after every small task). `make test-fast` must pass before each commit.
- Hooks: saving a `.py` file runs ruff and the related deterministic tests (`scripts/hooks/run_related_tests.sh`). Saving a frontend `.ts/.tsx` runs tsc and eslint. Every save runs the secret guard. Logs go to `logs/hooks/`.
- `make eval` runs the evaluation harness (real LLM, 3 scenarios × N runs) and writes `docs/evaluation.md`.
