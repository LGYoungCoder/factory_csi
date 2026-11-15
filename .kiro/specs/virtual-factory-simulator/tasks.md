# Implementation Plan

- [x] 1. factory_data core
  - Enums, timeutil, ids (incl. verification ids), schema (12 tables with CHECK and FK constraints), db engine helper with foreign keys enabled.
  - _Requirements: 2, 3, 4, 9.5, 13_
- [x] 2. World state models and batch Append_Function
  - Pydantic World_State, bias evaluation, lookups, load/save; `append.py` batch insert in one transaction with validation.
  - _Requirements: 11, 20_
- [x] 3. Factory config and baseline generator
  - Config validation, orders, products, routing, process steps, ST-20 measurements, EOL tests (no-flip rule), reference checks, state events, consistency validation.
  - _Requirements: 1, 5, 6, 7, 9_
- [x] 4. Scenario modifiers A, B, C and ground truth
  - Drift, program change and mix/routing shift; historical retests; world state per scenario; `simulator.ground_truth` models and writer.
  - _Requirements: 12, 14, 15, 16_
- [x] 5. Writer, hashing, registry, reset, CLI, signal summary
  - Atomic directory writes, Content_Hash, registry with pinned seeds, reset without ground truth, `python -m simulator generate`, `make seed`.
  - _Requirements: 8, 10, 17, 18, 19, 21_
- [x] 6. Module test suite
  - Reproducibility, integrity, routing, timestamps, scenario statistics, isolation scan, property tests; tune default seeds until all pass.
  - _Requirements: 22_
