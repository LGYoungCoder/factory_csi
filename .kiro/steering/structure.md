---
inclusion: always
---
# Project structure

Design reference: `docs/architecture.md`. Specs: `.kiro/specs/{virtual-factory-simulator, industrial-mcp-server, investigation-engine, verification-loop, investigation-api, investigation-workspace-ui, delivery-and-evaluation}`.

```
factory_data/   shared schema, ids, timeutil, enums, world_state, append (bottom layer)
simulator/      generator, scenarios, registry, reset, CLI; simulator.ground_truth = answer key
industrial_mcp/ MCP server (queries/ read tools, verification/ the only world-state reader)
backend/        settings, llm/, analytics/, evidence/, agent/, mcp_client/, store/, api/
evaluation/     eval harness (may read ground truth)
frontend/       React app
tests/          unit/ integration/ llm/ eval/
scripts/hooks/  Kiro hook scripts
```

One-way dependencies (enforced by import-linter in `pyproject.toml`):
- `factory_data` imports nothing from the other packages.
- `backend` and `industrial_mcp` never import `simulator.ground_truth`, `simulator.cli` or `simulator.writer`.
- No product package imports `evaluation`.
- `industrial_mcp.queries` never imports `factory_data.world_state`.
- The backend reads factory data only through MCP tools.
