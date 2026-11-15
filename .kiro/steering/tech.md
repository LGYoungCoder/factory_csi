---
inclusion: always
---
# Tech stack

- Python 3.11+, single uv project (`pyproject.toml`, `uv.lock`). Libraries: SQLAlchemy Core, Pydantic v2, NumPy/SciPy/Pandas, FastAPI, LangGraph (+ langgraph-checkpoint-sqlite), LiteLLM, the official MCP Python SDK (FastMCP, stdio).
- LLM: LiteLLM model string from `.env`; default `deepseek/deepseek-flash`. Use JSON mode plus a Pydantic schema in the prompt, with at most 2 repair attempts.
- **No fallback mode:** if the LLM is unavailable, investigation is disabled and an error is shown. Never generate canned text that looks like model output.
- SQLite for factory data (`data/ds-xx/factory.db`) and app state (`var/app.db`, `var/checkpoints.db`).
- Frontend: React 19 + TypeScript (strict) + Vite + Tailwind v4 + shadcn/ui-style components + ECharts + TanStack Query.
- Make targets: `setup`, `seed`, `test-fast` (no LLM), `test` (real LLM), `lint`, `eval`, `dev-backend`, `dev-frontend`, `docker-up`, `check-submission`.
- In environments where PyPI is slow, install with `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`. Do not hard-code a mirror in config.
