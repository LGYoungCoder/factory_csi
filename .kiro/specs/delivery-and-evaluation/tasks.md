# Implementation Plan

- [ ] 1. Repository foundation
  - Add the root pyproject (uv, ruff, pytest `llm` marker, import-linter contracts), Makefile, .gitignore, .env.example, the MIT LICENSE, placeholder packages and a frontend scaffold.
  - _Requirements: 1, 2, 3, 4, 5_
- [ ] 2. Kiro steering, hooks and dev MCP config
  - Add the steering files, the three hook JSON files plus scripts (related tests, frontend check, secret guard) and `.kiro/settings/mcp.json`.
  - _Requirements: 6, 7, 8, 9_
- [ ] 3. Containerization
  - Add the backend and frontend Dockerfiles, the nginx config with SSE passthrough, the entrypoint that generates datasets, and docker-compose with healthcheck.
  - _Requirements: 10, 11_
- [ ] 4. Evaluation harness
  - `python -m evaluation`: N runs per scenario, auto-approve rank-1, metrics, results JSON and docs/evaluation.md.
  - _Requirements: 12, 13, 14_
- [ ] 5. Documentation
  - README, docs/architecture.md, demo-script, submission draft, dev-log, KIRO_USAGE.md.
  - _Requirements: 15, 16, 17_
- [ ] 6. Pre-submission checker, clean-clone check, optional CI, tooling tests
  - _Requirements: 18, 19, 20_
