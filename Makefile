SHELL := /bin/bash
RUNS ?= 3
DATASETS ?= ds-01,ds-02,ds-03

.PHONY: help setup seed test test-fast lint eval dev-backend dev-frontend docker-up check-submission

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install Python (uv) and frontend (npm) dependencies
	@command -v uv >/dev/null || { echo "uv not found (need uv >= 0.4)"; exit 1; }
	@command -v node >/dev/null || { echo "node not found (need Node >= 20)"; exit 1; }
	@command -v npm >/dev/null || { echo "npm not found (need npm >= 10)"; exit 1; }
	uv sync
	cd frontend && npm ci

seed: ## Generate datasets ds-00..ds-03 under data/
	uv run python -m simulator seed --out data

test-fast: ## Deterministic tests, import contracts, frontend tests and typecheck (no LLM)
	@rc=0; \
	uv run pytest -m "not llm" -q || rc=1; \
	uv run lint-imports || rc=1; \
	(cd frontend && npm run test --silent) || rc=1; \
	(cd frontend && npm run typecheck --silent) || rc=1; \
	exit $$rc

test: ## Everything in test-fast plus real-LLM tests (needs .env key, costs a few cents)
	@echo "NOTE: LLM tests call the provider configured in .env and cost a small amount of money."
	@rc=0; $(MAKE) --no-print-directory test-fast || rc=1; \
	uv run pytest -m "llm or not llm" -q || rc=1; exit $$rc

lint: ## ruff + eslint + tsc
	@rc=0; uv run ruff check . || rc=1; \
	(cd frontend && npm run lint --silent) || rc=1; \
	(cd frontend && npm run typecheck --silent) || rc=1; exit $$rc

eval: ## Evaluation harness with real LLM (RUNS=3 DATASETS=ds-01,ds-02,ds-03)
	uv run python -m evaluation --runs $(RUNS) --datasets $(DATASETS)

dev-backend: ## Run backend with reload (long-running, own terminal)
	uv run uvicorn backend.api.app:app --reload --host 127.0.0.1 --port 8000

dev-frontend: ## Run Vite dev server on :5173 (long-running, own terminal)
	cd frontend && npm run dev

docker-up: ## Build and start the Docker Compose stack on http://localhost:8080
	@test -f .env || { echo "Missing .env – run: cp .env.example .env"; exit 1; }
	docker compose up --build

check-submission: ## Pre-submission compliance checklist
	bash scripts/check_submission.sh
