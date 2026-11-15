---
inclusion: fileMatch
fileMatchPattern: ["simulator/**", "industrial_mcp/**", "factory_data/**"]
---
# Industrial data semantics

- **MES**: production_orders, products (SN, model, material lot), process_steps (station, equipment, recipe_version, times).
- **PPM / equipment monitoring**: process_measurements (ST-20 torque/angle with program_version), equipment_events (state/alarm/maintenance/calibration), process_changes (recipe/program changes).
- **EOL**: eol_tests (first test, retest via retest_of, origin), eol_measurements (output_voltage with limits), reference_sample_checks.
- **FAIL_Rate** = FAIL / total over first historical tests (`is_retest = false`, `origin = historical`).
- Timestamps are always `YYYY-MM-DDTHH:MM:SSZ` (UTC) through `factory_data.timeutil`. Windows are half-open `[start, end)`.
- ID formats: `PO-123456`, `SN-1234567`, `PS-12345678`, `PM-12345678`/`PM-V1234567`, `EQE-123456`, `PC-12345`, `T-123456`/`T-V12345`, `RC-12345`/`RC-V1234`. The `V` marks verification origin.
- Origin `historical` = generated, `verification` = appended by the simulated verification engine after approval.
- Three artifacts per dataset: `factory.db` (observable), `world_state.json` (hidden physics, read only by verification), `ground_truth.json` (answer key, tests/eval only). Observable data never contains scenario names, conclusion categories or answer-key fields.
- Physics: normalized z model with the no-flip rule (see docs/architecture.md §3).
