# Design Document – Investigation Engine

The shared design is in [docs/architecture.md](../../../docs/architecture.md), sections 6, 7 and 10.

## Components
- `backend/llm`: `client.py` (LiteLLM `acompletion` wrapper, budget counting, call records), `structured.py` (JSON mode, schema-in-prompt, Pydantic validation, ≤2 repairs, citation hook), `health.py` (ping + cache), `tools.py` (MCP → OpenAI tool schemas, allow-list), `redact.py`.
- `backend/analytics`: pure functions over MCP outputs (`anomaly.py`, `comparisons.py`, `process.py`, `msa.py`, `timeline.py`, `stats.py` for Fisher/KS/MWU/OLS).
- `backend/evidence`: `models.py` (EvidenceItem, Hypothesis), `registry.py` (sequential ids, finding_key idempotency), `citations.py` (validator + guardrails).
- `backend/agent`: `state.py` (TypedDict state), `graph.py` (StateGraph wiring), node modules, `prompts/` (plain text templates).

## Key decisions
- Analytics never calls the LLM. LLM prompts receive compact evidence digests (id, kind, title, summary, key numbers) capped at 24,000 characters.
- The Tool_Loop uses native tool calling. Each turn counts as one LLM call, and each executed tool counts as one MCP call.
- Events are written through a `CaseEventSink` interface implemented by `backend.store`, so the engine code does not depend on FastAPI.
