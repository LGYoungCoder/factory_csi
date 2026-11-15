# Design Document – Industrial MCP Server

The shared design is in [docs/architecture.md](../../../docs/architecture.md), section 5.

## Components
- `server.py`: FastMCP app; registers tools with Pydantic input/output models from `schemas.py`; wraps each tool with call-id assignment, validation, error mapping (`errors.py`) and JSONL call logging (`calllog.py`).
- `queries/`: one module per read tool; pure functions `(conn, args) -> output model`, read-only SQLite URI connection per call.
- `verification/engine.py`: the only reader of `world_state.json`; computes outcomes, appends rows through `factory_data.append`; `ledger.py` holds approval idempotency and a file lock.

## Key decisions
- Error transport: tool raises `ToolError(code, message, details)` → returned as an MCP `isError` result whose text is the JSON error body.
- Half-open windows `[start, end)`; floats rounded (rates 4 dp, measurements 3 dp); stable ordering everywhere.
- Simulated verification clock and deterministic noise as in the architecture doc, with the no-flip rule reused from `factory_data`.
- Dev-time registration: `.kiro/settings/mcp.json` with four servers `industrial-mcp-ds-00..03`.

## Testing
`tests/integration/mcp/` using `mcp.client.stdio` against datasets generated into a temp dir; verification outcomes compared with ground truth.
