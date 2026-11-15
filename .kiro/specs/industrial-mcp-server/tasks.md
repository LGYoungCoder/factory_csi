# Implementation Plan

- [ ] 1. Server skeleton
  - FastMCP app, CLI args, schemas module, structured errors, call-id and JSONL call log wrapper, per-call read-only connection.
  - _Requirements: 1, 2, 3, 4, 16, 17_
- [ ] 2. Read tools
  - get_factory_context, get_eol_summary, get_product_traces, get_equipment_events, get_process_changes, get_reference_sample_checks, get_source_records.
  - _Requirements: 5, 6, 7, 8, 9, 10_
- [ ] 3. Simulated verification
  - Engine (cross_retest, reference_sample_check, process_config_check), simulated clock, deterministic noise, batch append, approval ledger with lock.
  - _Requirements: 11, 12, 13, 14_
- [ ] 4. Isolation and module tests
  - Import contracts, audit-hook test, stdio integration tests including verification outcomes against ground truth.
  - _Requirements: 15, 18_
