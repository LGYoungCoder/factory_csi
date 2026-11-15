# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent investigates End-of-Line (EOL) quality anomalies in the fictional Factory Alpha by querying simulated MES, PPM (equipment monitoring) and EOL systems. This spec covers only the Industrial MCP Server, the Python package `industrial_mcp/`. It is a real Model Context Protocol server built with the official MCP Python SDK (FastMCP) over the stdio transport. One server process serves exactly one Dataset and exposes eight typed tools: seven read-only query tools over the Factory_DB and one tool that executes a human-approved simulated verification and appends verification-origin records.

The server is used on two paths that must stay distinct:
- Runtime_Path: the Backend starts one Industrial_MCP_Server process per Dataset with `python -m industrial_mcp --dataset <dataset_id> --data-dir <dir>` and keeps one long-lived stdio MCP session per Dataset. This is the only path the investigation product uses.
- Dev_Registration: the same server command is registered in `.kiro/settings/mcp.json` as four entries, `industrial-mcp-ds-00` to `industrial-mcp-ds-03`, one per Dataset, so that Kiro's development agent can call the tools while developers debug data and tool behavior. The Backend does not read `.kiro/settings/mcp.json`, and no runtime component depends on that file.

The Backend obtains all Factory_DB data, for investigations and for dashboard endpoints, exclusively through this server's tools. The dashboard overview, equipment detail and trend views are served from `get_factory_context`, `get_eol_summary` and `get_equipment_events` results, and the Backend does not read `factory.db` directly.

In scope: CLI entry point and startup checks, the eight tools with Pydantic input and output schemas, input validation, structured tool errors, response envelope, determinism rules, the simulated verification engine (cross-retest, reference sample check, process configuration check), approval idempotency, the call log, reset tolerance, information isolation from the answer key, performance limits and the deterministic test suite.

Out of scope: authentication and authorization, HTTP or SSE MCP transports, any write other than verification-origin rows written through the Append_Function, real device, PLC, MES or network integration, the approval workflow and UI, the decision which tools the LLM may see, and the Reset_Function itself.

Assumptions:
- A Time_Window is half-open: a record belongs to the window when start <= ts < end.
- The equipment type returned by `get_factory_context` is derived from the Station of the equipment: ST-10 → `component_assembly`, ST-20 → `bolt_tightening`, ST-30 → `functional_assembly`, EOL test station → `eol_tester`.
- The factory name and line name are taken from the default Factory_Config, because the twelve Factory_DB tables do not store them.
- The measurement noise of simulated verifications uses the standard deviation that the default Factory_Config defines for EOL `output_voltage` measurements and for Reference_Sample_Check measurements.
- The nominal value, sample_id and test_item of a simulated Reference_Sample_Check are copied from the earliest historical Reference_Sample_Check of the same EOL_Tester. In all four generated Datasets each EOL_Tester has at least one historical check.
- The Factory_DB schema is fixed to twelve tables, so approval_id cannot be stored in the Factory_DB. It is persisted in a Verification_Ledger file under the Log_Dir. A ledger entry is honored only while the Factory_DB still contains the verification-origin rows the entry depends on, so entries from before a Reset_Function call stop applying to writing verifications. Residual limitation: an entry for a Non_Writing_Verification executed while the Factory_DB had no verification-origin rows stays live after a reset. This is harmless because its outcome depends only on World_State fields that the Reset_Function regenerates byte-identically. The Backend is expected to issue a new approval_id for every approval.
- Only Writing_Verifications advance the Verification_Sequence_Number, because the sequence number is derived from rows in the Factory_DB. Non_Writing_Verifications report the Verification_Timestamp of the current sequence number without consuming it.
- The Backend does not call the Reset_Function while a `run_simulated_verification` call on the same Dataset is in progress.
- The Reference_Sample_Tolerance of an EOL_Tester is returned by the reference sample check, because a real tester displays the acceptance limit of a reference check. It is the only Tester-related World_State number the server returns.

Dependencies on other specs:
- virtual-factory-simulator: the Schema (Requirement 2), ID_Formats including the verification identifier function (Requirement 3), Time_Util (Requirement 4), shared enums (Requirement 13), the World_State models and Tester_Bias evaluation (Requirement 11), the Scenario_Registry and its default seeds (Requirement 18), the Reset_Function with atomic file replacement (Requirement 19), the batch Append_Function (Requirement 20 criteria 1 to 7), which commits all rows of one call, up to 5 EOL tests with their measurements plus any reference sample checks, in a single transaction, the named failure_code constant for a failing `output_voltage` measurement (Requirement 20 criterion 8), and the import-linter contract that forbids `industrial_mcp` from importing `simulator.ground_truth` (Requirement 21). The Industrial_MCP_Server makes exactly one Append_Function call per Writing_Verification.
- investigation-engine, investigation-api and verification-loop (the Backend): own the MCP session lifecycle, approval_id issuance, and the restriction that `get_source_records` and `get_equipment_events` with `include_measurements=true` are not exposed to the LLM. This spec enforces neither restriction.

## Glossary

- **Industrial_MCP_Server**: The MCP server implemented in the Python package `industrial_mcp/`, started with `python -m industrial_mcp`, serving one Dataset over stdio.
- **MCP_Client**: Any client that connects to the Industrial_MCP_Server over stdio, for example the Backend or the Dev_Agent.
- **Backend**: The investigation backend defined in the investigation-engine, investigation-api and verification-loop specs.
- **Runtime_Path**: The production use of the Industrial_MCP_Server: the Backend starts one server process per Dataset and holds one long-lived stdio session to it.
- **Dev_Agent**: Kiro's development agent, which calls the Industrial_MCP_Server during development through the Dev_Registration.
- **Dev_Registration**: The server entries in `.kiro/settings/mcp.json` that start the Industrial_MCP_Server for the Dev_Agent.
- **Dataset**: The set of artifacts of one scenario stored under `<data-dir>/<dataset_id>/`, as defined in the virtual-factory-simulator spec.
- **Dataset_ID**: An opaque identifier of a Dataset: `ds-00`, `ds-01`, `ds-02` or `ds-03`.
- **Data_Dir**: The directory given by `--data-dir` (default `data`) that contains one subdirectory per Dataset_ID.
- **Log_Dir**: The directory given by `--log-dir` (default `logs`) under which the Industrial_MCP_Server writes the Call_Log and the Verification_Ledger.
- **Factory_DB**: The SQLite file `<data-dir>/<dataset_id>/factory.db` containing the twelve observable tables defined by the Schema.
- **Schema**: The twelve-table definition in the Factory_Data_Package: `stations`, `equipment`, `product_models`, `production_orders`, `products`, `process_steps`, `process_measurements`, `equipment_events`, `process_changes`, `eol_tests`, `eol_measurements` and `reference_sample_checks`.
- **Factory_Data_Package**: The shared Python package `factory_data/` providing the Schema, ID_Formats, Time_Util, enums, World_State models and the Append_Function.
- **Factory_Config**: The Simulator configuration of Factory Alpha; this spec uses only its default instance.
- **World_State**: The hidden physical truth of a Dataset: True_Value per SN, Tester_Bias functions, approved and actual recipe and program configuration per Station equipment, and reference sample availability, reason and Reference_Sample_Tolerance per EOL_Tester.
- **World_State_File**: The file `<data-dir>/<dataset_id>/world_state.json`, the serialized World_State.
- **Ground_Truth**: The answer key of a Dataset, including the affected SN set and expected verification outcomes.
- **Ground_Truth_File**: The file `<data-dir>/<dataset_id>/ground_truth.json`, the serialized Ground_Truth.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ` representing an instant in UTC.
- **Time_Util**: The Factory_Data_Package module that formats and parses every UTC_Timestamp.
- **ID_Formats**: The Factory_Data_Package module that validates identifiers of the types order_id, sn, step_id, meas_id, event_id, change_id, test_id and check_id, and generates verification-origin identifiers.
- **EOL_Tester**: One of the two EOL test equipment units, EOL-A or EOL-B.
- **Station_Equipment**: The equipment unit of ST-10, ST-20 or ST-30.
- **SN**: The serial number of one product.
- **True_Value**: The physical `output_voltage` value of one SN stored in the World_State.
- **Tester_Bias**: The time-dependent additive offset of an EOL_Tester, defined in the World_State by a base offset, an optional onset UTC_Timestamp and a slope.
- **FAIL_Rate**: For a set of EOL tests, the number of tests with result FAIL divided by the number of tests in the set.
- **Origin**: The column of `eol_tests` and `reference_sample_checks` with value `historical` or `verification`.
- **First_Historical_Test**: An `eol_tests` row with is_retest false and Origin `historical`.
- **Historical_Retest**: An `eol_tests` row with is_retest true and Origin `historical`.
- **Reference_Sample_Check**: A measurement of a known reference sample on an EOL_Tester, recorded in `reference_sample_checks`, where deviation equals measured minus nominal.
- **Reference_Sample_Tolerance**: For one EOL_Tester, the positive number stored in the World_State that gives the largest absolute Reference_Sample_Check deviation that counts as within tolerance.
- **Append_Function**: The Factory_Data_Package function that appends verification-origin `eol_tests`, `eol_measurements` and `reference_sample_checks` rows to a Factory_DB. One call appends a batch of up to 5 EOL tests and any reference sample checks in a single transaction.
- **Reset_Function**: The Simulator function that atomically replaces the Factory_DB and World_State_File of a Dataset with freshly generated content.
- **Scenario_Registry**: The Simulator component that lists each Dataset_ID with its Scenario_Key, user-facing label, description and default seed.
- **Conclusion_Category**: The shared enum with values TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **Query_Tool**: One of the seven read-only tools `get_factory_context`, `get_eol_summary`, `get_product_traces`, `get_equipment_events`, `get_process_changes`, `get_reference_sample_checks` and `get_source_records`.
- **Verification_Tool**: The tool `run_simulated_verification`.
- **Verification_Module**: The submodule `industrial_mcp.verification`, the only part of the Industrial_MCP_Server that reads the World_State.
- **Query_Modules**: The subpackage `industrial_mcp.queries` that implements the Query_Tools.
- **Writing_Verification**: A simulated verification that appends rows to the Factory_DB: a cross-retest, or a reference sample check on an EOL_Tester whose reference sample is AVAILABLE.
- **Non_Writing_Verification**: A simulated verification that appends no rows: a process configuration check, or a reference sample check on an EOL_Tester whose reference sample is UNAVAILABLE.
- **Time_Window**: The half-open interval from a `start` UTC_Timestamp (inclusive) to an `end` UTC_Timestamp (exclusive).
- **Bucket**: One sub-interval of a Time_Window: bucket i covers start + i × bucket_minutes (inclusive) to the earlier of start + (i + 1) × bucket_minutes and end (exclusive), for i = 0, 1, … until the bucket start reaches end.
- **Data_Time_Range**: The minimum and maximum of every timestamp column value of every historical record in the Factory_DB, where historical records are all rows of `production_orders`, `products`, `process_steps`, `process_measurements`, `equipment_events` and `process_changes`, plus the `eol_tests` and `reference_sample_checks` rows with Origin `historical`.
- **Record_Ref**: A string `<table>:<primary_key>` that identifies one row of one Schema table, for example `eol_tests:T-000123`.
- **Call_ID**: The identifier `MCP-<n>` of one tools/call request within one server process.
- **Tool_Error**: A tools/call result with `isError` true that carries an error object with an Error_Code.
- **Error_Code**: One of INVALID_ARGUMENT, NOT_FOUND, UNAVAILABLE, LIMIT_EXCEEDED and INTERNAL.
- **Call_Log**: The append-only JSON Lines file `<log-dir>/mcp/<dataset_id>.jsonl` with one line per tools/call.
- **Verification_Ledger**: The append-only JSON Lines file `<log-dir>/mcp/verifications/<dataset_id>.jsonl` that records every executed simulated verification with its approval_id.
- **Verification_Lock**: An exclusive advisory file lock on `<log-dir>/mcp/verifications/<dataset_id>.lock`, shared by all server processes that serve the same Dataset with the same Log_Dir.
- **Live_Ledger_Entry**: A Verification_Ledger entry whose recorded prior refs and created refs all exist in the current Factory_DB as rows with Origin `verification`.
- **Approval_ID**: The `approval_id` argument of the Verification_Tool: the identifier of the human approval that authorizes one verification.
- **Verification_Sequence_Number**: For one Verification_Tool call, 1 plus the number of distinct ts values among all `eol_tests` and `reference_sample_checks` rows with Origin `verification` in the Factory_DB when the call starts executing.
- **Verification_Timestamp**: The simulated time of one verification: the Data_Time_Range end plus 10 minutes multiplied by the Verification_Sequence_Number.
- **Verification_Noise**: The deterministic zero-mean measurement noise added to a simulated measurement.
- **Verification_ID**: The identifier of one simulated verification: `VER-` followed by the first 12 characters, in uppercase, of the hexadecimal SHA-256 digest of the UTF-8 string `<dataset_id>:<approval_id>`.
- **Industrial_MCP_Test_Suite**: The deterministic tests of the Industrial_MCP_Server under `tests/unit` and `tests/integration`.

## Requirements

### Requirement 1: Server Process, Transport and Registration

**User Story:** As a backend developer, I want one stdio MCP server process per Dataset, so that the Backend can keep one long-lived standard MCP session per Dataset.

#### Acceptance Criteria

1. WHEN a user runs `python -m industrial_mcp --dataset <dataset_id> --data-dir <dir> [--log-dir <dir>]`, THE Industrial_MCP_Server SHALL start an MCP server built with the official MCP Python SDK (FastMCP) that communicates only over stdio and serves only the Dataset in `<data-dir>/<dataset_id>/`. `--data-dir` SHALL default to `data` and `--log-dir` SHALL default to `logs`, both resolved relative to the working directory.
2. THE Industrial_MCP_Server SHALL write only MCP JSON-RPC messages to standard output and SHALL write all diagnostic output to standard error.
3. IF `--dataset` is missing or is not exactly one of the Dataset_IDs listed in the Scenario_Registry (`ds-00`, `ds-01`, `ds-02`, `ds-03`, case-sensitive, without trimming), THEN THE Industrial_MCP_Server SHALL print an error naming the rejected value and listing the four valid Dataset_IDs to standard error and exit with status code 2 before reading any MCP message.
4. IF at startup the directory `<data-dir>/<dataset_id>/` does not exist, or its `factory.db` does not exist or cannot be opened read-only as an SQLite database, THEN THE Industrial_MCP_Server SHALL print an error naming the Dataset_ID and the missing or unreadable artifact name to standard error and exit with status code 1 before reading any MCP message.
5. IF the resolved directory `<log-dir>/mcp/` lies inside the resolved directory `<data-dir>/<dataset_id>/`, THEN THE Industrial_MCP_Server SHALL print an error stating that logs must not be written inside a Dataset directory and exit with status code 2.
6. THE Industrial_MCP_Server SHALL provide no HTTP or SSE transport, SHALL open no listening socket and SHALL reject any command-line option other than `--dataset`, `--data-dir`, `--log-dir` and `--help` with exit status code 2.
7. WHEN standard input reaches end of file, THE Industrial_MCP_Server SHALL exit with status code 0 within 5 seconds.
8. THE repository SHALL contain a Dev_Registration in `.kiro/settings/mcp.json` with exactly four server entries named `industrial-mcp-ds-00`, `industrial-mcp-ds-01`, `industrial-mcp-ds-02` and `industrial-mcp-ds-03`. Each entry SHALL start the Industrial_MCP_Server with `uv run python -m industrial_mcp --dataset <dataset_id> --data-dir data`, and no entry SHALL list `run_simulated_verification` in its auto-approve list.
9. THE Industrial_MCP_Server SHALL behave identically when started through the Dev_Registration and through the Runtime_Path: it SHALL provide no command-line option, environment variable or tool that exists only for one of the two paths.

### Requirement 2: Tool Catalog and Schemas

**User Story:** As an agent developer, I want a fixed, self-describing tool catalog, so that the agent and the Backend can call tools with typed arguments and parse typed results.

#### Acceptance Criteria

1. WHEN an MCP_Client sends a tools/list request, THE Industrial_MCP_Server SHALL return exactly eight tools named `get_factory_context`, `get_eol_summary`, `get_product_traces`, `get_equipment_events`, `get_process_changes`, `get_reference_sample_checks`, `get_source_records` and `run_simulated_verification`, and no other tool.
2. THE Industrial_MCP_Server SHALL declare for each tool an `inputSchema` generated from a Pydantic model. The schema SHALL list every parameter with its JSON type, bounds, enum values and default value, SHALL mark every parameter without a default as required, and SHALL set `additionalProperties` to false.
3. THE Industrial_MCP_Server SHALL declare for each tool an `outputSchema` generated from a Pydantic model. Every successful tools/call result SHALL carry `structuredContent` that validates against that `outputSchema`, and one text content item containing the same JSON object.
4. THE Industrial_MCP_Server SHALL annotate each Query_Tool with `readOnlyHint` true and `openWorldHint` false, and the Verification_Tool with `readOnlyHint` false, `destructiveHint` false, `idempotentHint` true and `openWorldHint` false.
5. WHEN an MCP_Client sends a resources/list, resources/templates/list or prompts/list request, THE Industrial_MCP_Server SHALL return an empty list.
6. THE Industrial_MCP_Server SHALL give each tool an English description of 1 to 1024 characters that states the units of returned values (volts, N·m, degrees, minutes) and the half-open Time_Window rule where the tool takes a Time_Window.
7. THE Industrial_MCP_Server SHALL keep every tool name, tool description and schema text free of the following, compared case-insensitively: a scenario name, a Scenario_Registry label or description, the Scenario_Key `baseline`, a Conclusion_Category value, and the substrings `ground_truth`, `ground truth`, `world_state`, `world state` and `true_value`.
8. THE Industrial_MCP_Server SHALL serve every tool, including `get_source_records` and `get_equipment_events` with `include_measurements` true, to any MCP_Client. The description of `get_source_records` SHALL state that it resolves Record_Refs to raw rows; hiding it or raw measurement access from the LLM is the responsibility of the Backend.

### Requirement 3: Input Validation and Structured Errors

**User Story:** As an agent developer, I want strict validation and machine-readable errors, so that the agent can correct a bad call instead of receiving wrong data.

#### Acceptance Criteria

1. WHEN a tool receives a timestamp argument, THE Industrial_MCP_Server SHALL parse it with the Time_Util parse function. IF parsing fails, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT whose details name the field and the expected form `YYYY-MM-DDTHH:MM:SSZ`.
2. IF a tool receives a `start` that is not strictly earlier than its `end`, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT whose details name both fields.
3. WHEN a tool receives an identifier of a type covered by ID_Formats (sn, test_id and the primary keys listed in Requirement 10 criterion 1), THE Industrial_MCP_Server SHALL validate it with the ID_Formats validation function and SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT for a value the function rejects.
4. WHEN a tool receives an `equipment_id` or `model_id`, THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT if the value is empty, longer than 64 characters or contains whitespace, and a Tool_Error with Error_Code NOT_FOUND if the value is well-formed but matches no row of `equipment` or `product_models`.
5. IF a tool receives a `tester_id` or `target_tester_id` other than exactly `EOL-A` or `EOL-B`, an enum argument outside its allowed values (case-sensitive), an integer outside its allowed range, a value of the wrong JSON type (including a boolean or a numeric string where an integer is expected), an empty list where at least one entry is required, or a property not declared in the `inputSchema`, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT.
6. IF a list argument has more entries than its maximum, or a Time_Window with the given `bucket_minutes` yields more than 200 Buckets, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code LIMIT_EXCEEDED whose details name the field, the received size and the maximum.
7. WHEN a tools/call violates more than one rule of criteria 1 to 6, THE Industrial_MCP_Server SHALL list every violation in `details.violations`, ordered by field path, and SHALL use INVALID_ARGUMENT as the Error_Code if any violation is an INVALID_ARGUMENT violation and LIMIT_EXCEEDED otherwise.
8. THE Industrial_MCP_Server SHALL validate all arguments before it opens the Factory_DB, so that an invalid call returns INVALID_ARGUMENT or LIMIT_EXCEEDED even while the Dataset files are missing.
9. THE Industrial_MCP_Server SHALL represent every Tool_Error as a tools/call result with `isError` true and exactly one text content item containing a JSON object with the fields `error_code`, `message` (1 to 500 characters), optional `details` (a JSON object), `call_id` and `dataset_id`. This SHALL also apply to argument validation failures detected by the MCP SDK and to a tools/call that names an unknown tool, which SHALL return INVALID_ARGUMENT.
10. IF the Factory_DB, or for the Verification_Tool the World_State_File, is missing, unreadable, not a valid SQLite database or JSON document, or lacks a Schema table at the time of a call, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code UNAVAILABLE whose details name the artifact by file name only.
11. IF an unexpected exception occurs while a tool executes, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INTERNAL and a fixed generic message, and SHALL write the stack trace to standard error only.
12. THE Industrial_MCP_Server SHALL keep every Tool_Error message and details free of stack traces, the text `Traceback`, SQL statement text, absolute or relative filesystem paths, and the Data_Dir and Log_Dir values.
13. IF a tools/call returns a Tool_Error, THEN THE Industrial_MCP_Server SHALL leave the Factory_DB and the Verification_Ledger unchanged by that call.

### Requirement 4: Response Envelope and Determinism

**User Story:** As a backend developer, I want a uniform envelope and deterministic results, so that tool calls are traceable and tests and reports are repeatable.

#### Acceptance Criteria

1. THE Industrial_MCP_Server SHALL include in every tools/call result, successful or Tool_Error, a `call_id` of the form `MCP-<n>`, where n is a decimal integer without leading zeros that starts at 1 for the first tools/call received by the process and increases by 1 for every subsequent tools/call, so that every Call_ID is unique within one server process.
2. THE Industrial_MCP_Server SHALL include in every tools/call result a `dataset_id` equal to the `--dataset` value of the process.
3. THE Industrial_MCP_Server SHALL produce every timestamp value in a tool result with the Time_Util format function.
4. THE Industrial_MCP_Server SHALL express every FAIL_Rate and every other ratio as a fraction from 0 to 1 rounded to 4 decimal places, and every measured value, limit, nominal, deviation, tolerance and statistic rounded to 3 decimal places, using Python's built-in `round`. Rows returned by `get_source_records` are exempt and keep their stored values.
5. IF the denominator of a FAIL_Rate is zero or a statistic is undefined, THEN THE Industrial_MCP_Server SHALL return null for that value, and SHALL never return NaN or Infinity.
6. THE Industrial_MCP_Server SHALL include a `ref` field holding the Record_Ref of the source row in every row-level record it returns from a Schema table.
7. FOR ALL pairs of Query_Tool calls with identical arguments against Factory_DBs whose twelve tables contain identical rows, THE Industrial_MCP_Server SHALL return `structuredContent` that is identical in every field except `call_id`, including when the two calls are served by different server processes.
8. THE Industrial_MCP_Server SHALL order every list in a tool result by the rule stated in the requirement for that tool, and by ascending primary key where no rule is stated.
9. THE Industrial_MCP_Server SHALL keep every tool result free of Scenario_Registry labels, descriptions and Scenario_Keys, so that the Dataset_ID is the only dataset identifier an MCP_Client receives.

### Requirement 5: Factory Context Tool

**User Story:** As an investigator agent, I want the factory structure and data time range, so that I can plan valid queries.

#### Acceptance Criteria

1. WHEN `get_factory_context` is called with no arguments, THE Industrial_MCP_Server SHALL return the factory name and line name from the default Factory_Config, the `stations` rows (station_id, name) ordered by station_id, the `equipment` rows (equipment_id, station_id, name, equipment_type) ordered by equipment_id, the `product_models` rows (model_id, name, `output_voltage` lower_limit, upper_limit and unit `V`) ordered by model_id, the Data_Time_Range as `data_time_range.start` and `data_time_range.end`, and the `dataset_id`.
2. THE Industrial_MCP_Server SHALL derive equipment_type from the station_id of the equipment row using the mapping ST-10 → `component_assembly`, ST-20 → `bolt_tightening`, ST-30 → `functional_assembly` and the EOL test station → `eol_tester`.
3. THE Industrial_MCP_Server SHALL compute the Data_Time_Range from historical records only, so that appending verification-origin rows leaves `data_time_range` unchanged.
4. THE Industrial_MCP_Server SHALL return a `verification_records` object with the number of `eol_tests` rows and the number of `reference_sample_checks` rows with Origin `verification`, and the latest ts among them, or null when there are none.
5. IF `get_factory_context` receives any argument, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT.
6. THE Industrial_MCP_Server SHALL return from `get_factory_context` a `record_counts` object with `product_count` (the number of `products` rows), `first_historical_test_count` (the number of First_Historical_Tests), `retest_count` (the number of Historical_Retests), `verification_eol_test_count` (the number of `eol_tests` rows with Origin `verification`) and `verification_reference_check_count` (the number of `reference_sample_checks` rows with Origin `verification`), each computed from the current Factory_DB content at call time.

### Requirement 6: EOL Summary Tool

**User Story:** As an investigator agent, I want aggregated EOL results by tester, model and time, so that I can locate where and when the failure rate changed.

#### Acceptance Criteria

1. WHEN `get_eol_summary` is called with `start` and `end`, optional `tester_id`, optional `model_id` and optional `bucket_minutes` (integer from 15 to 240 inclusive, default 60), THE Industrial_MCP_Server SHALL compute every count, FAIL_Rate, Bucket and failure code statistic of criteria 2 to 5 over the First_Historical_Tests with ts in the Time_Window that match the given `tester_id` and `model_id` filters.
2. THE Industrial_MCP_Server SHALL return a `totals` object, a `by_tester` list, a `by_model` list and a `by_tester_model` list, each entry with test_count, pass_count, fail_count and fail_rate. `by_tester` SHALL list every EOL_Tester allowed by the filter and `by_model` every product model allowed by the filter, including entries with test_count 0, and `by_tester_model` SHALL list every combination of those, ordered by tester_id then model_id.
3. THE Industrial_MCP_Server SHALL return a `buckets` list with one entry per EOL_Tester allowed by the filter and per Bucket of the Time_Window, including empty Buckets, ordered by tester_id then bucket_start, each with tester_id, bucket_start, bucket_end, test_count, pass_count, fail_count and fail_rate, so that the Backend can serve per-tester FAIL_Rate trends for its dashboard from this list.
4. THE Industrial_MCP_Server SHALL return a `top_failure_codes` list of at most 10 entries (failure_code, count) over the FAIL First_Historical_Tests, ordered by count descending then failure_code ascending, and the number of distinct failure codes.
5. THE Industrial_MCP_Server SHALL return a `failed_sn_sample` list of the FAIL First_Historical_Tests ordered by ts ascending then sn ascending, limited to the first 50 entries, each with sn, test_id, ref, tester_id, model_id, ts and failure_code, together with `failed_sn_total` (the number of FAIL First_Historical_Tests) and `failed_sn_truncated` (true when failed_sn_total is greater than 50).
6. THE Industrial_MCP_Server SHALL return a `retest_summary` over the Historical_Retests with ts in the Time_Window whose retest tester_id and model_id match the filters, with test_count, pass_count, fail_count and a `by_tester_pair` list ordered by original_tester_id then retest_tester_id, where original_tester_id is the tester_id of the `eol_tests` row referenced by retest_of.
7. THE Industrial_MCP_Server SHALL return a `verification_summary` over the `eol_tests` rows with Origin `verification` and ts in the Time_Window that match the filters, with test_count, pass_count, fail_count and a `by_tester` list.
8. THE Industrial_MCP_Server SHALL exclude Historical_Retests and verification-origin tests from every value of criteria 2 to 5, and SHALL count each of them only in criterion 6 or criterion 7.
9. WHEN no First_Historical_Test matches the filters, THE Industrial_MCP_Server SHALL return a successful result with zero counts, null fail_rate values, Buckets with zero counts and empty `top_failure_codes` and `failed_sn_sample` lists.
10. FOR ALL valid argument combinations, THE Industrial_MCP_Server SHALL return counts equal to the counts of a direct SQL query over the same Factory_DB with the same filters, and FAIL_Rates equal to fail count divided by test count rounded to 4 decimal places (numeric parity property).

### Requirement 7: Product Traces Tool

**User Story:** As an investigator agent, I want the full manufacturing and test history of selected SNs, so that I can correlate failures with process data.

#### Acceptance Criteria

1. WHEN `get_product_traces` is called with `serial_numbers` (1 to 20 strings), THE Industrial_MCP_Server SHALL remove duplicate entries and return one trace per SN found in `products`, in order of first occurrence in the input.
2. THE Industrial_MCP_Server SHALL include in each trace the product (sn, order_id, model_id, material_lot, created_ts), the production order (order_id, qty, start_ts) and the product model `output_voltage` limits, each with its ref.
3. THE Industrial_MCP_Server SHALL include in each trace every `process_steps` row of the SN ordered by start_ts then step_id, with step_id, station_id, equipment_id, start_ts, end_ts, recipe_version, result and ref.
4. THE Industrial_MCP_Server SHALL include in each trace every `process_measurements` row of the SN ordered by ts then meas_id, with meas_id, step_id, equipment_id, ts, parameter, value, unit, program_version and ref.
5. THE Industrial_MCP_Server SHALL include in each trace every `eol_tests` row of the SN of either Origin, including Historical_Retests, ordered by ts then test_id, with test_id, tester_id, ts, model_id, result, failure_code, is_retest, retest_of, origin and ref, and with the `eol_measurements` rows of each test ordered by meas_id, each with meas_id, test_item, value, lower_limit, upper_limit, result and ref.
6. WHEN some well-formed SNs do not exist in `products`, THE Industrial_MCP_Server SHALL return them in a `not_found` list in order of first occurrence, alongside the traces of the found SNs.
7. IF none of the requested SNs exists in `products`, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code NOT_FOUND whose details contain the `not_found` list.
8. IF any entry of `serial_numbers` fails the ID_Formats validation for sn, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT naming every invalid entry, and IF more than 20 entries are given, THEN it SHALL return LIMIT_EXCEEDED.

### Requirement 8: Equipment Events Tool

**User Story:** As an investigator agent, I want equipment events and process measurement statistics for one equipment unit, so that I can detect alarms, calibrations and parameter shifts.

#### Acceptance Criteria

1. WHEN `get_equipment_events` is called with `equipment_id`, `start`, `end`, optional `event_types` (1 to 4 values from `state`, `alarm`, `maintenance`, `calibration`; duplicates removed), optional `include_measurements` (boolean, default false) and optional `bucket_minutes` (integer from 15 to 240 inclusive, default 60), THE Industrial_MCP_Server SHALL return the `equipment_events` rows of that equipment with ts in the Time_Window and event_type in the filter, ordered by ts then event_id, each with event_id, equipment_id, ts, event_type, severity, details (the details_json value parsed as JSON) and ref.
2. THE Industrial_MCP_Server SHALL return at most 500 events, together with `event_total_count` and `events_truncated` (true when event_total_count is greater than 500).
3. THE Industrial_MCP_Server SHALL return a `measurement_stats` list over the `process_measurements` rows of that equipment with ts in the Time_Window, with one entry per Bucket, parameter and program_version that contains at least one row, ordered by bucket_start, parameter and program_version. Each entry SHALL contain bucket_start, bucket_end, parameter, unit, program_version, count, mean, std (sample standard deviation with one degree of freedom, null when count is below 2), min, p5, median, p95 and max, with percentiles computed by linear interpolation between closest ranks.
4. WHEN the equipment has no `process_measurements` rows in the Time_Window, including ST-10, ST-30 and EOL_Tester equipment, THE Industrial_MCP_Server SHALL return an empty `measurement_stats` list.
5. WHEN `include_measurements` is true, THE Industrial_MCP_Server SHALL return a `measurements` list of the raw `process_measurements` rows of criterion 3 ordered by ts then meas_id, limited to 2000 rows, each with meas_id, step_id, sn, ts, parameter, value, unit, program_version and ref, together with `measurement_total_count` and `measurements_truncated` (true when measurement_total_count is greater than 2000).
6. WHEN `include_measurements` is false, THE Industrial_MCP_Server SHALL return null for `measurements`, `measurement_total_count` and `measurements_truncated`.
7. THE Industrial_MCP_Server SHALL accept as `equipment_id` of `get_equipment_events` every row of `equipment`, that is the Station_Equipment of ST-10, ST-20 and ST-30 and the EOL_Testers EOL-A and EOL-B, and SHALL apply criteria 1 to 6 to each of them, so that the Backend can serve the equipment detail view of its dashboard for any equipment through this tool.
8. WHEN `get_equipment_events` is called for ST-10 or ST-30 Station_Equipment, THE Industrial_MCP_Server SHALL return a `step_counts` list with one entry per Bucket of the Time_Window, using the same `bucket_minutes` argument (integer from 15 to 240 inclusive, default 60) and the same Bucket rules as criterion 3, including empty Buckets, ordered by bucket_start, each entry being `{bucket_start, bucket_end, step_count, by_result}`, where step_count is the number of `process_steps` rows of that equipment with start_ts in the Bucket and by_result maps each result value of those rows to its count, together with `step_total_count`, the number of `process_steps` rows of that equipment with start_ts in the Time_Window.
9. WHEN `get_equipment_events` is called for ST-20 Station_Equipment, THE Industrial_MCP_Server SHALL either return `step_counts` and `step_total_count` computed as in criterion 8 or return null for both, and WHEN it is called for an EOL_Tester, THE Industrial_MCP_Server SHALL return null for `step_counts` and `step_total_count`.
10. WHEN `get_equipment_events` is called for ST-20 Station_Equipment with `include_measurements` true and the full Data_Time_Range of a Dataset of 800 products generated with the Scenario_Registry default seed, THE Industrial_MCP_Server SHALL return all 1,600 raw `process_measurements` rows (one torque row and one angle row per ST-20 process step), which is within the 2000-row limit of criterion 5, with `measurement_total_count` 1600 and `measurements_truncated` false.

### Requirement 9: Process Change and Reference Sample Check Tools

**User Story:** As an investigator agent, I want process changes and reference sample checks, so that I can test process and measurement hypotheses, including when evidence is absent.

#### Acceptance Criteria

1. WHEN `get_process_changes` is called with `start`, `end` and optional `equipment_id`, THE Industrial_MCP_Server SHALL return the `process_changes` rows with ts in the Time_Window that match the equipment filter, ordered by ts then change_id, each with change_id, equipment_id, ts, change_type, old_value, new_value, changed_by and ref, together with `count`.
2. WHEN `get_reference_sample_checks` is called with `tester_id`, `start` and `end`, THE Industrial_MCP_Server SHALL return the `reference_sample_checks` rows of that EOL_Tester with ts in the Time_Window and either Origin, ordered by ts then check_id, each with check_id, tester_id, ts, sample_id, test_item, nominal, measured, deviation, result, origin and ref, together with `count`, `historical_count` and `verification_count`.
3. WHEN no row matches the arguments of `get_process_changes` or `get_reference_sample_checks`, THE Industrial_MCP_Server SHALL return a successful result with an empty list and `count` 0, and SHALL NOT return a Tool_Error.
4. THE Industrial_MCP_Server SHALL return from `get_reference_sample_checks` no Reference_Sample_Tolerance, no reference sample availability and no other World_State value.

### Requirement 10: Source Records Tool

**User Story:** As a backend developer, I want to resolve Record_Refs to raw rows, so that every evidence citation in a report can be traced to the Factory_DB.

#### Acceptance Criteria

1. WHEN `get_source_records` is called with `refs` (1 to 50 strings), THE Industrial_MCP_Server SHALL split each ref at its first colon into a table name and a primary key, SHALL accept only the twelve Schema table names (exact, case-sensitive), and SHALL validate the primary key with ID_Formats for the tables `production_orders` (order_id), `products` (sn), `process_steps` (step_id), `process_measurements` and `eol_measurements` (meas_id), `equipment_events` (event_id), `process_changes` (change_id), `eol_tests` (test_id) and `reference_sample_checks` (check_id), and as a non-empty string of at most 64 characters without whitespace for `stations`, `equipment` and `product_models`.
2. IF any ref lacks a colon, names a table outside the Schema or has a primary key that fails criterion 1, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT listing every offending ref with the reason, and SHALL return no rows.
3. THE Industrial_MCP_Server SHALL remove duplicate refs and return one entry per ref in order of first occurrence, each with ref, table, status (`FOUND` or `NOT_FOUND`) and row, where row is an object of every Schema column of that table with its stored value, or null when the status is `NOT_FOUND`.
4. THE Industrial_MCP_Server SHALL return a successful result when some or all refs are `NOT_FOUND`.
5. THE Industrial_MCP_Server SHALL look up rows only with parameterized queries against a fixed mapping from table name to primary key column, and SHALL execute no SQL text supplied by an MCP_Client.
6. FOR ALL Record_Refs returned by any other tool, THE Industrial_MCP_Server SHALL return status `FOUND` from `get_source_records` with column values that equal the values in the response that emitted the ref, after applying the rounding of Requirement 4 criterion 4 (ref resolution property).

### Requirement 11: Simulated Verification Common Contract

**User Story:** As a quality engineer, I want approved verifications executed deterministically against the simulated plant, so that new evidence is reproducible and clearly marked as simulated.

#### Acceptance Criteria

1. WHEN `run_simulated_verification` is called, THE Industrial_MCP_Server SHALL require `verification_type` (`cross_retest`, `reference_sample_check` or `process_config_check`), a `params` object, `approval_id` and `approved_by`, and SHALL validate `params` against the Pydantic model of the given `verification_type` with no additional properties allowed.
2. IF `approval_id` is missing or does not match the pattern `^[A-Za-z0-9_-]{1,64}$`, or `approved_by` is missing, empty, longer than 64 characters, consists only of whitespace or contains a control character, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT and write no row.
3. THE Industrial_MCP_Server SHALL compute the Verification_Sequence_Number and the Verification_Timestamp of a call while holding the Verification_Lock, and SHALL write every row of a Writing_Verification with ts equal to that Verification_Timestamp, so that each Writing_Verification adds exactly one new distinct verification ts and the Verification_Sequence_Number returns to 1 after the Reset_Function removes all verification-origin rows.
4. WHEN a Non_Writing_Verification executes, THE Industrial_MCP_Server SHALL report the Verification_Timestamp of the current Verification_Sequence_Number and write no row, so that the next Writing_Verification uses the same Verification_Sequence_Number.
5. THE Verification_Module SHALL draw each Verification_Noise value from a normal distribution with mean 0 and the standard deviation the default Factory_Config defines for the measurement type, using a pseudo-random generator seeded with an integer derived by SHA-256 from the Scenario_Registry default seed of the Dataset_ID, the Verification_Sequence_Number, the verification_type and the measured subject (the SN for a cross-retest, the tester_id for a reference sample check). The noise SHALL be independent of wall-clock time, process ID, approval_id and approved_by.
6. THE Verification_Module SHALL evaluate Tester_Bias at the Verification_Timestamp with the Factory_Data_Package evaluation function and SHALL load the World_State_File anew in every Verification_Tool call.
7. THE Industrial_MCP_Server SHALL write all rows of one Writing_Verification with exactly one batch Append_Function call, which commits them in a single transaction. IF any write fails, THEN THE Industrial_MCP_Server SHALL persist none of the rows of that call and return a Tool_Error.
8. THE Industrial_MCP_Server SHALL hold the Verification_Lock from the computation of the Verification_Sequence_Number until the Verification_Ledger entry is written, so that Verification_Tool calls on the same Dataset from different processes, such as the Backend and the Dev_Agent, execute one at a time. IF the lock cannot be acquired within 10 seconds, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code UNAVAILABLE and write no row.
9. WHEN a verification completes, THE Industrial_MCP_Server SHALL return `simulation` true, `verification_id` (the Verification_ID), `verification_type`, `approval_id`, `approved_by`, `sequence_number`, `verification_ts`, the type-specific outcome fields, `created_refs` (the Record_Refs of every row written, ordered by table then primary key, empty for a Non_Writing_Verification), `summary` (a text of at most 300 characters built from a fixed template and the outcome values only), `replayed`, `call_id` and `dataset_id`.
10. THE Verification_Module SHALL read only the World_State_File and the Factory_DB, SHALL write only through the Append_Function and to the Verification_Ledger, and SHALL contain no code path that opens a network connection, starts a subprocess or accesses a device.
11. THE Industrial_MCP_Server SHALL modify and delete no existing Factory_DB row during a verification and SHALL insert only rows with Origin `verification` and their `eol_measurements` rows.

### Requirement 12: Cross-Retest Verification

**User Story:** As a quality engineer, I want to retest selected SNs on a chosen tester, so that I can separate a product defect from a measurement problem.

#### Acceptance Criteria

1. WHEN `run_simulated_verification` is called with `verification_type` `cross_retest`, THE Industrial_MCP_Server SHALL require `params.serial_numbers` (1 to 5 unique SNs) and `params.target_tester_id` (`EOL-A` or `EOL-B`).
2. IF `params.serial_numbers` contains a duplicate, an SN that fails ID_Formats validation, or an SN that exists in `products` but has no First_Historical_Test, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT naming each offending SN and write no row for any SN of the call.
3. IF `params.serial_numbers` names a well-formed SN absent from `products`, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code NOT_FOUND naming each missing SN and write no row for any SN of the call.
4. IF `params.serial_numbers` has more than 5 entries, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code LIMIT_EXCEEDED and write no row.
5. THE Verification_Module SHALL compute for each SN a measured `output_voltage` equal to the World_State True_Value of the SN plus the Tester_Bias of the target tester at the Verification_Timestamp plus Verification_Noise, rounded to 3 decimal places, and SHALL set the result to PASS when the rounded value is greater than or equal to the lower limit and less than or equal to the upper limit of the SN's product model in `product_models`, and to FAIL otherwise.
6. THE Industrial_MCP_Server SHALL append for each SN one `eol_tests` row with the target tester_id, ts equal to the Verification_Timestamp, the model_id of the SN, result as in criterion 5, failure_code null for PASS and, for FAIL, the named `output_voltage` failure_code constant of the Factory_Data_Package (the value the Simulator writes for a failing `output_voltage` measurement), is_retest true, retest_of equal to the test_id of the latest existing `eol_tests` row of that SN by ts then test_id (of either Origin), and Origin `verification`, plus one `eol_measurements` row with test_item `output_voltage`, the rounded value, the model limits and the result.
7. THE Industrial_MCP_Server SHALL return a `results` list in input order with, per SN: sn, model_id, target_tester_id, the First_Historical_Test (test_id, tester_id, result), retest_of, the new test ref, measured_value, lower_limit, upper_limit and result, plus `pass_count` and `fail_count`.
8. THE Industrial_MCP_Server SHALL build the cross-retest summary from the template `Simulated cross-retest on <target_tester_id>: <pass_count> PASS, <fail_count> FAIL of <n> SN(s).`
9. THE Industrial_MCP_Server SHALL accept a target tester equal to the tester of the First_Historical_Test of an SN.
10. THE Industrial_MCP_Server SHALL return no True_Value, no Tester_Bias value and no Verification_Noise value in the cross-retest result.

### Requirement 13: Reference Sample and Process Configuration Verifications

**User Story:** As a quality engineer, I want to check a tester against its reference sample and audit a station's configuration, so that I can confirm or rule out tester drift and unapproved process changes.

#### Acceptance Criteria

1. WHEN `run_simulated_verification` is called with `verification_type` `reference_sample_check` and `params.tester_id` (`EOL-A` or `EOL-B`), and the World_State reference sample of that EOL_Tester is UNAVAILABLE, THE Industrial_MCP_Server SHALL return a successful result with outcome `UNAVAILABLE`, the World_State reason, empty `created_refs` and the summary `Simulated reference sample check on <tester_id>: UNAVAILABLE (<reason>).`, and SHALL write no row.
2. WHEN the reference sample of the EOL_Tester is AVAILABLE, THE Verification_Module SHALL compute measured equal to the nominal plus the Tester_Bias of that EOL_Tester at the Verification_Timestamp plus Verification_Noise, rounded to 3 decimal places, and deviation equal to measured minus nominal rounded to 3 decimal places, where nominal, sample_id and test_item come from the earliest historical Reference_Sample_Check of that EOL_Tester by ts then check_id.
3. WHEN the reference sample is AVAILABLE, THE Industrial_MCP_Server SHALL append one `reference_sample_checks` row with Origin `verification`, ts equal to the Verification_Timestamp, result PASS when the absolute deviation is less than or equal to the Reference_Sample_Tolerance and FAIL otherwise, and SHALL return outcome `WITHIN_TOLERANCE` for PASS or `OUT_OF_TOLERANCE` for FAIL, with tester_id, sample_id, test_item, nominal, measured, deviation, tolerance, result, the check ref and the summary `Simulated reference sample check on <tester_id>: <outcome> (deviation <deviation> V, tolerance <tolerance> V).`
4. IF the reference sample is AVAILABLE and the EOL_Tester has no historical Reference_Sample_Check, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INTERNAL and write no row.
5. THE Industrial_MCP_Server SHALL return no Tester_Bias base offset, onset, slope or Tester_Bias value in the reference sample check result.
6. WHEN `run_simulated_verification` is called with `verification_type` `process_config_check` and `params.equipment_id` naming a Station_Equipment, THE Industrial_MCP_Server SHALL return the World_State approved recipe_version and program_version, the World_State actual recipe_version and program_version, a match flag per field, outcome `MATCH` when both fields are equal and `MISMATCH` otherwise, empty `created_refs` and the summary `Simulated configuration audit of <equipment_id>: <outcome>.`, and SHALL write no row.
7. IF `params.equipment_id` of a `process_config_check` names an EOL_Tester, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT, and IF it is well-formed but absent from `equipment`, THEN it SHALL return NOT_FOUND.

### Requirement 14: Approval Idempotency

**User Story:** As a backend developer, I want repeated calls with the same approval to have no additional effect, so that a retried request never doubles the evidence.

#### Acceptance Criteria

1. WHEN a verification completes successfully, THE Industrial_MCP_Server SHALL append one line to the Verification_Ledger containing approval_id, approved_by, verification_type, the validated params in canonical form (sorted keys), `prior_refs` (the sorted Record_Refs of all `eol_tests` and `reference_sample_checks` rows with Origin `verification` that existed before the call), `created_refs` and the complete result except `call_id` and `replayed`, written as one newline-terminated JSON line in a single append while holding the Verification_Lock.
2. WHEN `run_simulated_verification` is called with an approval_id that equals the approval_id of a Live_Ledger_Entry with the same verification_type, canonical params and approved_by, THE Industrial_MCP_Server SHALL return the stored result with `replayed` true and a new `call_id`, and SHALL write no Factory_DB row and no Verification_Ledger line.
3. IF `run_simulated_verification` is called with an approval_id of a Live_Ledger_Entry whose verification_type, canonical params or approved_by differ from the call, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INVALID_ARGUMENT whose details state that the approval_id was already used for a different verification, and SHALL write no row.
4. WHEN a Verification_Ledger entry is not a Live_Ledger_Entry, for example because the Reset_Function removed its rows, THE Industrial_MCP_Server SHALL ignore that entry, so that a call with the same approval_id executes as a new verification.
5. WHEN a new server process starts for a Dataset, THE Industrial_MCP_Server SHALL honor the Live_Ledger_Entries written by earlier processes with the same Log_Dir.
6. THE Industrial_MCP_Server SHALL set `replayed` false on the first execution of a verification.
7. IF the Verification_Ledger contains a malformed line other than a final line without a newline terminator, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INTERNAL for Verification_Tool calls and write no row. A final line without a newline terminator SHALL be ignored.
8. IF appending to the Verification_Ledger fails after the Factory_DB rows were committed, THEN THE Industrial_MCP_Server SHALL return a Tool_Error with Error_Code INTERNAL and write the Verification_ID and created Record_Refs to standard error.
9. THE Industrial_MCP_Server SHALL write no True_Value, Tester_Bias value, Tester_Bias parameter or Verification_Noise value to the Verification_Ledger.

### Requirement 15: Information Isolation

**User Story:** As the system designer, I want the server isolated from the answer key and from hidden truth outside verification, so that the investigator agent cannot learn the answer from tool output.

#### Acceptance Criteria

1. THE Industrial_MCP_Server SHALL NOT import `simulator.ground_truth` directly or indirectly, and the import-linter contract of the virtual-factory-simulator spec (Requirement 21 criterion 3) SHALL pass with `lint-imports` exit status 0.
2. THE Industrial_MCP_Server SHALL never open a file named `ground_truth.json`, neither at startup nor during any tool call.
3. THE project SHALL define an import-linter forbidden contract that forbids the Query_Modules from importing `factory_data.world_state` and `industrial_mcp.verification`, and `lint-imports` SHALL exit with status 0.
4. WHILE executing a Query_Tool, THE Industrial_MCP_Server SHALL NOT open the World_State_File.
5. THE Industrial_MCP_Server SHALL return from its tools, and write to the Call_Log, only these World_State-derived values: reference sample availability and reason, Reference_Sample_Tolerance, approved and actual recipe and program versions, and measured values, deviations and results computed by the Verification_Module. It SHALL return no True_Value, no Tester_Bias value or parameter, and no raw World_State_File content.
6. THE Industrial_MCP_Server SHALL return no tool result field named `true_value`, `bias`, `base_offset`, `onset` or `slope`, and no text value containing a Conclusion_Category value or the substrings `ground_truth` or `world_state`.

### Requirement 16: Call Log

**User Story:** As a developer, I want a log of every tool call, so that I can audit what the agent asked and how the server answered.

#### Acceptance Criteria

1. WHEN a tools/call completes with a successful result or a Tool_Error, THE Industrial_MCP_Server SHALL append exactly one JSON line to the Call_Log `<log-dir>/mcp/<dataset_id>.jsonl` with the fields `ts` (wall-clock completion time as a UTC_Timestamp from Time_Util), `server_started_at` (wall-clock process start as a UTC_Timestamp), `call_id`, `dataset_id`, `tool`, `arguments`, `status` (`ok` or `error`), `error_code` (null when status is `ok`), `duration_ms` (non-negative integer from request receipt to response) and `result_bytes` (UTF-8 byte length of the serialized result JSON).
2. WHEN the Call_Log directory does not exist, THE Industrial_MCP_Server SHALL create it before the first append.
3. WHEN the JSON serialization of the arguments of a call exceeds 4096 characters, THE Industrial_MCP_Server SHALL write the first 4096 characters as a string in `arguments` and set `arguments_truncated` to true; otherwise it SHALL write the arguments as received and set `arguments_truncated` to false.
4. THE Industrial_MCP_Server SHALL write no tool result body and no World_State content to the Call_Log.
5. THE Industrial_MCP_Server SHALL write each Call_Log line with one append-mode write, so that lines from concurrent processes serving the same Dataset, such as the Backend and the Dev_Agent, are never interleaved.
6. IF appending to the Call_Log fails, THEN THE Industrial_MCP_Server SHALL still return the tool result unchanged and write a warning to standard error.
7. THE Industrial_MCP_Server SHALL create, modify or delete no file under `<data-dir>/<dataset_id>/` other than the Factory_DB changes made by the Append_Function.

### Requirement 17: Reset Tolerance, Connections and Performance

**User Story:** As a backend developer, I want the server to see reset data immediately and answer quickly, so that a new investigation session can start without restarting the server.

#### Acceptance Criteria

1. THE Industrial_MCP_Server SHALL open a new SQLite connection to the Factory_DB for every tools/call, SHALL enable foreign key enforcement on it before executing any statement, and SHALL close it before returning the result.
2. THE Industrial_MCP_Server SHALL open the Factory_DB for every Query_Tool in SQLite read-only mode (`mode=ro` URI), so that any write attempt on that connection fails.
3. THE Industrial_MCP_Server SHALL keep the SQLite rollback journal mode of the Factory_DB unchanged and SHALL NOT enable write-ahead logging, so that after every call the Dataset directory contains exactly `factory.db`, `world_state.json` and `ground_truth.json`.
4. THE Industrial_MCP_Server SHALL cache no Factory_DB row and no World_State content between tools/call requests.
5. WHEN the Reset_Function has replaced the Factory_DB and World_State_File between two tools/call requests, THE Industrial_MCP_Server SHALL answer the second request from the regenerated content without a restart, so that `verification_records` counts are 0 and the next Verification_Sequence_Number is 1.
6. WHEN the Factory_DB becomes readable again after a call returned UNAVAILABLE, THE Industrial_MCP_Server SHALL answer the next call from the Factory_DB without a restart.
7. WHEN any Query_Tool is called with valid arguments, including the full Data_Time_Range and `include_measurements` true, against a Dataset of 800 products generated with the Scenario_Registry default seed, THE Industrial_MCP_Server SHALL return the result within 2 seconds of wall-clock time measured at the MCP_Client on a developer laptop, excluding server startup.
8. WHEN the Verification_Tool is called with valid arguments against such a Dataset, THE Industrial_MCP_Server SHALL return the result within 5 seconds of wall-clock time measured at the MCP_Client.

### Requirement 18: Deterministic Test Suite

**User Story:** As a developer, I want automated deterministic tests through a real MCP client, so that tool contracts and verification outcomes are proven without an LLM.

#### Acceptance Criteria

1. THE Industrial_MCP_Test_Suite SHALL carry no pytest `llm` marker, SHALL be selected by `pytest -m "not llm"`, and SHALL pass with network access disabled and without any LLM API credential.
2. THE Industrial_MCP_Test_Suite SHALL run its integration tests through a real stdio MCP client from the MCP Python SDK that starts `python -m industrial_mcp` as a subprocess against Datasets `ds-00` to `ds-03` generated with the Scenario_Registry default seeds into a temporary Data_Dir, with a temporary Log_Dir.
3. THE Industrial_MCP_Test_Suite SHALL verify that tools/list returns exactly the eight tools of Requirement 2 with input and output schemas, and that every successful result in the suite validates against the tool's `outputSchema`.
4. THE Industrial_MCP_Test_Suite SHALL verify for each Dataset that every count and FAIL_Rate of `get_eol_summary` equals a direct SQL computation over the same Factory_DB, for the full Data_Time_Range without filters, for each `tester_id`, for each `model_id`, and for `bucket_minutes` 15, 60 and 240.
5. THE Industrial_MCP_Test_Suite SHALL collect every Record_Ref returned by every tool during a sweep of all tools on each Dataset, and SHALL verify that `get_source_records` resolves each one with status `FOUND` and matching column values.
6. THE Industrial_MCP_Test_Suite SHALL verify, reading the Ground_Truth_File in the test process only, that the simulated verifications return the Ground_Truth expected outcomes:
   - `ds-01`: a cross-retest on EOL-A of the first 5 affected SNs by sn returns PASS for each SN; a reference sample check on EOL-B returns OUT_OF_TOLERANCE; a process configuration check of the ST-20 equipment returns MATCH.
   - `ds-02`: a cross-retest of the first 5 affected SNs by sn whose First_Historical_Test is FAIL, on the EOL_Tester other than the one of that test, returns FAIL for each SN; a reference sample check on each EOL_Tester returns WITHIN_TOLERANCE; a process configuration check of the ST-20 equipment returns MISMATCH.
   - `ds-03`: a reference sample check on EOL-B returns UNAVAILABLE with no row written; a cross-retest on EOL-A of the first 5 affected SNs by sn returns FAIL for each SN; a process configuration check of each Station_Equipment returns MATCH.
7. THE Industrial_MCP_Test_Suite SHALL verify reproducibility: a fixed sequence of at least four verifications that includes both Writing_Verifications and Non_Writing_Verifications, executed on a Dataset, then executed again with different approval_ids after a Reset_Function call on the same running server, SHALL return results equal in every field except `call_id`, `verification_id` and `approval_id`, including identical `created_refs`, `sequence_number`, `verification_ts` and measured values.
8. THE Industrial_MCP_Test_Suite SHALL verify that Query_Tool results with identical arguments are identical except `call_id` across two separate server processes on the same Dataset.
9. THE Industrial_MCP_Test_Suite SHALL verify idempotency: a repeated call with the same approval_id and arguments returns `replayed` true and the original result while Factory_DB row counts stay unchanged; a reuse with different params returns INVALID_ARGUMENT; a replay after a server restart returns `replayed` true; and a cross-retest call reusing an approval_id after a Reset_Function call executes as a new verification.
10. THE Industrial_MCP_Test_Suite SHALL verify each Error_Code except INTERNAL on at least one tool: INVALID_ARGUMENT for a malformed timestamp, `start` not before `end`, an invalid enum, an invalid identifier, an undeclared property and a missing approval_id; LIMIT_EXCEEDED for 21 serial_numbers, 51 refs, 6 cross-retest SNs and more than 200 Buckets; NOT_FOUND for all-unknown SNs and an unknown equipment_id; UNAVAILABLE while `factory.db` is temporarily renamed. It SHALL also verify that no error message or details contain `Traceback` or the temporary Data_Dir or Log_Dir path, and that no failed call changes Factory_DB row counts.
11. THE Industrial_MCP_Test_Suite SHALL start the server under a Python audit hook that records file open and socket connect events, run the full sweep including verifications, and verify that no file named `ground_truth.json` was opened, that `world_state.json` was opened only during Verification_Tool calls, that no socket connection was made, and that `simulator.ground_truth` was never loaded in the server process.
12. THE Industrial_MCP_Test_Suite SHALL verify that a Query_Tool call after a Reset_Function call on a running server returns the regenerated content, and that after the full sweep each Dataset directory contains exactly `factory.db`, `world_state.json` and `ground_truth.json`.
13. THE Industrial_MCP_Test_Suite SHALL verify the response time limits of Requirement 17 criteria 7 and 8 on the `ds-00` to `ds-03` Datasets.
