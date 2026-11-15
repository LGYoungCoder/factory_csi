# Design Document – Investigation API

The shared design is in [docs/architecture.md](../../../docs/architecture.md), sections 7 and 8.

## Components
- `backend/settings.py` (pydantic-settings), `backend/api/app.py` (lifespan: store init, MCP manager, LLM health loop, restart recovery), `routes_*.py`, `sse.py`, `errors.py`, `status_rules.py`.
- `backend/mcp_client/manager.py`: one `ClientSession` per dataset held in an `AsyncExitStack`; `asyncio.Lock` per session; restart + single retry for read tools; records `mcp_calls`.
- `backend/store`: SQLAlchemy Core tables, async access via `asyncio.to_thread` on a sync engine (SQLite, WAL), `events.py` appends case events with per-case seq and notifies SSE subscribers through an in-process `asyncio.Condition`.

## Key decisions
- Graph runs as an `asyncio` background task per case; at most one active case per dataset (checked in a transaction).
- SSE: replay from store after `Last-Event-ID`/`after`, then wait on the condition; heartbeat every 15 s; close after `completed`.
- Dashboard endpoints call MCP tools and reuse `backend.analytics.detect_anomaly`.
