---
inclusion: always
---
# Security boundaries

- Secrets live only in `.env` (git-ignored). Never write a key into code, docs, tests, logs, commit messages or tool output. Mask keys when reporting them.
- `backend` and `industrial_mcp` never import or read ground truth (`simulator.ground_truth`, `ground_truth.json`). Only `industrial_mcp.verification` reads `world_state.json`.
- Scenario labels and descriptions are UI-only. They never enter LLM prompts.
- The system never controls real equipment. Every verification is simulated, requires an explicit human approve decision, and is labelled `"simulation": true`.
- When the LLM is unavailable, produce no fallback or invented text. Surface the error and disable investigation.
- Reports and the UI use "suspected" or "evidence-supported" wording and never claim a confirmed root cause.
- The API binds to 127.0.0.1 by default and has no auth (local demo). Do not expose it publicly without adding protection.
