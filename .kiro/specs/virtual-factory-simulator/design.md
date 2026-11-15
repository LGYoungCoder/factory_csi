# Design Document – Virtual Factory Simulator

The shared technical design is in [docs/architecture.md](../../../docs/architecture.md), sections 1–4. This document records only the decisions specific to this module.

## Components
- `factory_data/`: `schema.py` (12 SQLAlchemy Core tables with CHECK constraints), `ids.py` (formats, validation, verification id generator), `timeutil.py`, `enums.py`, `world_state.py` (Pydantic models + bias evaluation), `append.py` (batch Append_Function, one transaction), `db.py` (engine factory with `PRAGMA foreign_keys=ON`).
- `simulator/`: `config.py` (Factory_Config + validation), `generator.py` (baseline generator, one `numpy.random.Generator` seeded from the seed), `scenarios.py` (modifiers a/b/c as parameter overrides + post-processing hooks), `writer.py` (temp dir → atomic swap), `hashing.py` (Content_Hash), `summary.py` (Signal_Summary from factory.db), `registry.py`, `reset.py`, `cli.py`, `ground_truth.py` (answer-key models + writer; imported only by `cli.py`/`writer` orchestration).

## Key decisions
- Physics uses the normalized z model and the no-flip rule (architecture §3).
- Scenario modifiers are data (`ScenarioParams`) plus small hook functions; the generator reads params, so A/B/C share one code path.
- Routing and model draws happen per product in release order; all random draws come from one generator in a fixed order, so the same seed gives the same rows.
- Writing: build the DB in `data/.tmp-<id>/`, close the engine (journal mode DELETE), then replace files with `os.replace`. Reset writes `factory.db` and `world_state.json` the same way and leaves `ground_truth.json` alone.
- Content_Hash: SHA-256 over canonical JSON of every table's rows ordered by PK, plus the bytes of both JSON files.
- Default seeds are chosen so that every statistical criterion holds. They are pinned in `registry.py` and asserted by the tests.

## Testing
pytest in `tests/unit/simulator/`, session-scoped fixtures generate the four datasets once; Hypothesis for time/ID/model round-trips.
