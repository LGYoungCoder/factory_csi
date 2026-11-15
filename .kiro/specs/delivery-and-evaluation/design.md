# Design Document – Delivery and Evaluation

The shared design is in [docs/architecture.md](../../../docs/architecture.md), sections 2 and 11.

## Components
- Root `pyproject.toml` (uv, ruff, pytest markers, import-linter contracts), `Makefile`, `.env.example`, `.gitignore`, `LICENSE` (MIT).
- `.kiro/steering/*.md`, `.kiro/hooks/*.json`, `.kiro/settings/mcp.json`, `scripts/hooks/*.sh`.
- `docker/backend.Dockerfile`, `docker/frontend.Dockerfile`, `docker/nginx.conf`, `docker/entrypoint.sh`, `docker-compose.yml`.
- `evaluation/` harness (`python -m evaluation --runs 3`), outputs `docs/evaluation.md`.
- `scripts/check_submission.sh`, `scripts/clean_clone_check.sh`.

## Key decisions
- Hook scripts accept the file path as `$1` and fall back to parsing STDIN JSON. They log to `logs/hooks/` and print a one-line summary.
- Ports are bound to 127.0.0.1 because the app has no login and spends LLM credits.
