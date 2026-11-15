# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent investigates End-of-Line (EOL) quality anomalies in the fictional Factory Alpha by querying simulated MES, PPM and EOL systems through the Industrial_MCP_Server. This spec covers the backend service that connects the pieces: the HTTP API (`backend/api`), the application store (`backend/store`), the MCP client layer (`backend/mcp_client`), application settings and the application lifecycle.

The Investigation_API serves the Investigation_Workspace_UI. It lists the Scenario_Registry entries, resets Datasets, computes deterministic factory dashboards (overview, equipment detail, trends), creates and tracks investigation Cases, streams Case progress over Server-Sent Events, accepts human approval Decisions, and serves evidence, reports and MCP call audit records. It runs the Investigation_Engine and the Verification_Loop graph as background tasks and owns the long-lived MCP sessions they use.

In scope:
- Settings loading and validation, startup, periodic LLM health refresh and graceful shutdown.
- The MCP_Client_Manager: one stdio session per available Dataset, timeouts, restart-and-retry, call recording.
- The Store: App_DB schema, repository functions and the append-only Case_Event log.
- All `/api/*` endpoints listed in the requirements below, their payloads, error mapping and limits.
- Concurrency rules, restart recovery, security boundaries and the integration and LLM test suites of this module.

Out of scope:
- Authentication, authorization, multi-user support and public deployment. The service is a local Docker Compose demo without authentication; this is a documented limitation.
- WebSocket transport and PDF report rendering.
- The investigation logic itself (graph nodes, prompts, analytics, hypotheses, verification planning, report content), which belongs to the Investigation_Engine and Verification_Loop specs.
- Dataset generation for missing Datasets, which belongs to `make seed` and the container entrypoint (delivery-and-evaluation spec).
- Any connection to real equipment, MES, PLC or SCADA systems.

Assumptions:
- The Case_Status model (CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM, FAILED) is defined by the verification-loop spec. The Active_Case statuses are CREATED, RUNNING, AWAITING_APPROVAL and CONCLUDING. CREATED is included so that the window between case insertion and graph start cannot admit a second case or a reset.
- FAILED_LLM is not an Active_Case status. A new Case MAY be created, and a reset MAY run, on a Dataset whose only non-terminal Case is FAILED_LLM. Either action increments the Dataset_Epoch, after which a retry of that FAILED_LLM Case is rejected with code DATASET_CHANGED (Requirement 18).
- The dashboard endpoints (overview, equipment detail, trends) obtain all Factory_DB data through the MCP_Client_Manager, using the Industrial_MCP_Server tools get_factory_context, get_eol_summary, get_equipment_events, get_process_changes and get_reference_sample_checks. These calls are recorded as MCP_Call_Records with case_id null and do not count against any Case_Budget. The backend never opens the Factory_DB, the World_State_File or the Ground_Truth_File itself.
- Dashboard statistics (FAIL_Rate, status rules, parameter statistics) use only rows with Origin `historical`. Verification-origin rows appear only in explicitly labeled lists.
- The Decision payload rules (Requirement 16) match the Decision model of the verification-loop spec: proposal_id is required for `approve` and forbidden for `reject_all` and `conclude`; note is required (1 to 500 characters) for `reject_all` and optional (at most 500 characters) for `approve` and `conclude`; actor is optional (at most 64 characters, default `engineer`); at most two `reject_all` Decisions per Case. The Investigation_API enforces these rules at the HTTP boundary.
- The Case_Budgets are owned by the Investigation_Engine and Verification_Loop: at most 20 MCP tool calls, 40 LLM calls, 3 verification rounds and 2 `reject_all` Decisions per Case. The Investigation_API reports them in the Case detail and enforces the `reject_all` limit at the HTTP boundary.
- This spec owns the Case_Event_Catalog. The Investigation_Engine and the Verification_Loop emit catalog events; the Investigation_API and the Store emit `status_changed`, `decision_recorded` and `completed`.
- The status thresholds in Requirement 12 are tuned against the registry default seeds. If a generated Dataset does not produce the expected colors in Requirement 12 criterion 9, the integration test fails and either the thresholds or the Dataset must be corrected.

Dependencies:
- virtual-factory-simulator: Factory_Data_Package (Schema, Time_Util, enums), Scenario_Registry, Reset_Function.
- industrial-mcp-server: `python -m industrial_mcp --dataset <id> --data-dir <dir>`, its eight tools, `call_id` on every response and the structured error codes INVALID_ARGUMENT, NOT_FOUND, UNAVAILABLE, LIMIT_EXCEEDED and INTERNAL.
- investigation-engine: LLM layer and LLM_Health_Status, Anomaly_Detector, Evidence_Item registry, hypotheses, graph segment 1, emission of Case_Event_Catalog events and the MCP and LLM call budget counters.
- verification-loop: Proposals, the human_approval interrupt and Decision model, Judgment_Changes, finalize_conclusion, report generation, the Case_Status model, the verification round and `reject_all` budgets, and retry from Checkpoint.
- Python 3.11+, FastAPI, pydantic-settings, SQLAlchemy Core, SQLite, the MCP Python SDK client and sse-starlette or an equivalent SSE response.

## Glossary

- **Investigation_API**: The FastAPI application `backend.api.app:app` and its `/api/*` endpoints.
- **App_Settings**: The pydantic-settings model that loads DATA_DIR, APP_DB_PATH, CHECKPOINT_DB_PATH, LOG_DIR, CORS_ORIGINS, HOST, PORT and the LLM_* settings from environment variables and an optional `.env` file.
- **Store**: The package `backend/store`, which defines the App_DB tables with SQLAlchemy Core and provides the repository functions used by the Investigation_API, the Investigation_Engine and the Verification_Loop.
- **App_DB**: The SQLite file at APP_DB_PATH holding Cases, Case_Events, Evidence_Items, Hypothesis_Snapshots, Proposals, Decisions, Judgment_Changes, Reports, MCP_Call_Records and LLM_Call_Records.
- **Checkpoint_DB**: The SQLite file at CHECKPOINT_DB_PATH used by the LangGraph checkpointer of the investigation graph.
- **Checkpoint**: A persisted graph state in the Checkpoint_DB keyed by Case_ID, from which a Case can be resumed.
- **Industrial_MCP_Server**: The MCP server process started with `python -m industrial_mcp --dataset <id> --data-dir <dir>`, serving exactly one Dataset over stdio.
- **MCP_Client_Manager**: The component in `backend/mcp_client` that owns one MCP_Session per Available_Dataset and exposes a typed async interface for the eight Industrial_MCP_Server tools.
- **MCP_Session**: One long-lived stdio MCP ClientSession connected to one Industrial_MCP_Server subprocess.
- **MCP_Session_Status**: The state of an MCP_Session: NOT_STARTED, STARTING, READY or FAILED.
- **MCP_Call_Record**: A row in the App_DB table `mcp_calls` describing one MCP tool call attempt.
- **MCP_Call_ID**: The `call_id` value returned by the Industrial_MCP_Server in a tool response.
- **MCP_Tool_Error**: A structured error returned by an Industrial_MCP_Server tool with one of the codes INVALID_ARGUMENT, NOT_FOUND, UNAVAILABLE, LIMIT_EXCEEDED or INTERNAL.
- **Transport_Failure**: A failure of the MCP_Session itself rather than of a tool: the subprocess exited, the stdio pipe closed, a protocol error occurred, or the call exceeded the MCP_Call_Timeout.
- **MCP_Call_Timeout**: The per-call time limit of the MCP_Client_Manager, 30 seconds by default.
- **LLM_Call_Record**: A row in the App_DB table `llm_calls` describing one LLM call with case_id, purpose, model, tokens_in, tokens_out, latency_ms and status.
- **Investigation_Engine**: The LLM investigation layer from the investigation-engine spec, including the LLM health check, the Anomaly_Detector and graph segment 1.
- **Verification_Loop**: The proposal, approval, verification, conclusion and report layer from the verification-loop spec.
- **Investigation_Workspace_UI**: The web front end from the investigation-workspace-ui spec, served from the origins in CORS_ORIGINS.
- **LLM_Health_Status**: The result of the Investigation_Engine LLM health check: status OK, UNAVAILABLE or MISCONFIGURED, model, provider, checked_at and an optional sanitized reason.
- **LLM_Status_Cache**: The most recent LLM_Health_Status held in memory by the Investigation_API.
- **Anomaly_Detector**: The deterministic Investigation_Engine function `detect_anomaly` in `backend.analytics`, as defined in the investigation-engine spec. The Overview and the status rules use that function unchanged, with the same thresholds and windows, applied to get_eol_summary results fetched through the MCP_Client_Manager; this spec does not define the algorithm.
- **Dataset**: The set of artifacts under `<DATA_DIR>/<dataset_id>/`, as defined in the virtual-factory-simulator spec.
- **Dataset_ID**: One of `ds-00`, `ds-01`, `ds-02` or `ds-03`.
- **Available_Dataset**: A Dataset listed in the Scenario_Registry whose `factory.db` exists under DATA_DIR as a regular file, determined from filesystem metadata without opening the file. Schema validation of the Factory_DB is performed by the Industrial_MCP_Server; a Dataset whose MCP_Session fails is reported through its MCP_Session_Status.
- **Dataset_Epoch**: A per-Dataset counter persisted in the App_DB, starting at 0 and incremented by 1 on every completed reset of the Dataset and on every Case creation on the Dataset.
- **Factory_DB**: The SQLite file `<DATA_DIR>/<dataset_id>/factory.db` containing observable system data only.
- **Factory_Data_Package**: The shared package `factory_data/` providing the Schema, Time_Util and shared enums.
- **Schema**: The SQLAlchemy Core table definitions of the Factory_DB in the Factory_Data_Package (twelve tables).
- **Time_Util**: The Factory_Data_Package module that formats and parses UTC_Timestamps.
- **Station**: One of ST-10, ST-20, ST-30 or the EOL test station of Line A.
- **Conclusion_Category**: The shared enum with values TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **World_State_File**: The file `<DATA_DIR>/<dataset_id>/world_state.json` containing hidden physical truth.
- **Ground_Truth_File**: The file `<DATA_DIR>/<dataset_id>/ground_truth.json` containing the answer key.
- **Scenario_Registry**: The Simulator component listing each Dataset with a Dataset_ID, a Scenario_Key, a user-facing label, a user-facing description and a default seed.
- **Scenario_Key**: The registry key of a Dataset: `baseline`, `a`, `b` or `c`.
- **Scenario_Label**: The user-facing label and user-facing description of a Scenario_Registry entry.
- **Reset_Function**: The Simulator function that atomically regenerates the Factory_DB and World_State_File of a Dataset from its registry default seed, without writing the Ground_Truth_File.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ` representing an instant in UTC, produced and parsed with the Time_Util.
- **EOL_Tester**: One of the two end-of-line test equipment units, EOL-A or EOL-B.
- **Origin**: The column on `eol_tests` and `reference_sample_checks` with value `historical` or `verification`.
- **FAIL_Rate**: For a given set of first (non-retest) historical EOL tests, the number of tests with result FAIL divided by the total number of tests in the set; null when the set is empty.
- **Reference_Sample_Check**: A row in `reference_sample_checks`, where deviation equals measured minus nominal.
- **Data_Time_Range**: For one Dataset, the interval from the earliest to the latest ts over historical `eol_tests` rows and `process_steps` start_ts values.
- **Recent_Window**: The last 60 minutes of the Data_Time_Range, from its end minus 60 minutes (inclusive) to its end (inclusive).
- **Baseline_Window**: The first 2 hours of the Data_Time_Range, from its start (inclusive) to its start plus 2 hours (exclusive), the same window the Anomaly_Detector uses as baseline.
- **Equipment_Status**: The dashboard color of one equipment unit: GREEN, ORANGE, RED or GREY.
- **Status_Reason**: An entry `{code, message}` explaining why an equipment unit has its Equipment_Status.
- **Overview**: The response of `GET /api/datasets/{id}/overview`.
- **Bucket**: A half-open time interval `[start, start + bucket_minutes)` aligned to the start of the Data_Time_Range; the last Bucket ends at or after the end of the Data_Time_Range.
- **Case**: One investigation of one Dataset, stored as a row in the App_DB table `cases`.
- **Case_ID**: The identifier of a Case: `CASE-` followed by a zero-padded sequence number of at least 4 digits, for example `CASE-0001`.
- **Case_Status**: The status of a Case: CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM or FAILED.
- **Active_Case**: A Case whose Case_Status is CREATED, RUNNING, AWAITING_APPROVAL or CONCLUDING.
- **Terminal_Status**: The Case_Status values COMPLETED, FAILED and FAILED_LLM, after which no graph task runs for the Case until a retry.
- **Case_Event**: A row in the App_DB table `case_events` with case_id, seq, type, payload JSON and created_at.
- **Event_Seq**: The `seq` of a Case_Event: a positive integer, starting at 1 and increasing by 1 for each new Case_Event of the same Case.
- **Case_Event_Catalog**: The canonical list of Case_Event types and payloads, owned by this spec, persisted with a per-Case Event_Seq and streamed over the Event_Stream: `status_changed {from, to, reason}`; `node_started {node}`; `node_completed {node, duration_ms}`; `mcp_call {mcp_call_id, tool, arguments_summary, status, error_code?, duration_ms}`; `llm_call {purpose, model, tokens_in, tokens_out, latency_ms, status}`; `anomaly_detected {anomalies: [{equipment_id, baseline_rate, window_rate, p_value}], detected_window}`; `evidence_added {evidence_id, kind, source_system, title}`; `hypotheses_updated {round, hypotheses}`; `support_downgraded {hypothesis_id, from, to, reason}`; `citation_dropped {item, invalid_ids}`; `awaiting_approval {round, proposals, conclude_option, final_round_of_suggestions, budgets}`; `proposal_rejected_by_validator {proposal, reason}`; `decision_recorded {action, proposal_id?, note?, actor}`; `verification_executed {proposal_id, approval_id, verification_id, outcomes_summary, evidence_ids}`; `verification_failed {proposal_id, approval_id, error_code}`; `judgment_changed {change}`; `judgment_change_unattributed {hypothesis_id}`; `conclusion_support_capped {from, to}`; `conclusion_finalized {conclusion}`; `report_generated {version}`; `budget_exhausted {budget}`; `error {code, message}`; `audit {name, actor, details}`, a generic type for audit-trail-only records emitted by other specs, where `name` identifies the record (for example `tool_call_rejected`, `tool_missing`, `analysis_skipped`, `verification_blocked_no_approval`, `loop_auto_concluded`, `narrative_unavailable` or `case_failed`), `actor` names who caused it (for example `system`) and `details` is a JSON object; and `completed {final_status}`, emitted once each time the Case reaches COMPLETED, FAILED or FAILED_LLM. The catalog contains 24 types. A field marked `?` is optional.
- **Progress_Event**: A Case_Event_Catalog event emitted by the Investigation_Engine or the Verification_Loop.
- **Case_Budget**: One of the per-Case limits: at most 20 MCP tool calls (`mcp_calls`), 40 LLM calls (`llm_calls`), 3 verification rounds (`verification_rounds`) and 2 `reject_all` Decisions (`reject_all`). Dashboard MCP calls with case_id null count against no Case_Budget.
- **Event_Stream**: The Server-Sent Events response of `GET /api/cases/{id}/events`.
- **Graph_Task**: The asyncio background task in which the Investigation_API runs or resumes the investigation graph for one Case.
- **Evidence_Item**: An evidence entry of a Case with an Evidence_ID (for example `EV-001`), a summary, a payload and a list of Record_Refs.
- **Record_Ref**: A reference to one Factory_DB row in the form `table:id`, for example `eol_tests:T-000123`.
- **Hypothesis_Snapshot**: The full list of hypotheses of a Case after one investigation round.
- **Proposal**: A verification action proposed by the Verification_Loop, identified by a proposal_id, awaiting human approval.
- **Decision**: A human approval input `{action, proposal_id, note, actor}` with action `approve`, `reject_all` or `conclude`, validated by the rules of Requirement 16.
- **Judgment_Change**: A recorded change of a hypothesis judgment after a verification round.
- **Report**: The 10-section report object of a Case together with its deterministic Markdown rendering, stored with a version number.
- **Error_Body**: The JSON error response `{"error": {"code": <string>, "message": <string>, "details": <object, optional>}}`.
- **Body_Limit**: The maximum accepted request body size, 65,536 bytes.
- **Secret_Value**: The value of any setting whose name ends in `_KEY`, `_TOKEN` or `_SECRET`, including the LLM API key.

## Requirements

### Requirement 1: Application Settings

**User Story:** As a developer running the demo, I want all paths, network settings and origins configurable from the environment, so that the same code runs locally and in Docker.

#### Acceptance Criteria

1. THE App_Settings SHALL load each setting from an environment variable of the same name, then from a `.env` file in the working directory, then from these defaults: DATA_DIR `./data`, APP_DB_PATH `./var/app.db`, CHECKPOINT_DB_PATH `./var/checkpoints.db`, LOG_DIR `./logs`, CORS_ORIGINS `http://localhost:5173`, HOST `127.0.0.1` and PORT `8000`. An environment variable SHALL take precedence over the `.env` file.
2. THE App_Settings SHALL parse CORS_ORIGINS as a comma-separated list of origins, trimming whitespace around each entry and ignoring empty entries.
3. IF PORT is not an integer from 1 to 65535, CORS_ORIGINS contains the entry `*`, or HOST is an empty string, THEN THE Investigation_API SHALL refuse to start and SHALL write an error to standard error that names the invalid setting without printing any Secret_Value.
4. WHEN the Investigation_API starts, THE Investigation_API SHALL create the parent directories of APP_DB_PATH and CHECKPOINT_DB_PATH and the LOG_DIR directory if they do not exist.
5. THE App_Settings SHALL pass the LLM_* settings to the Investigation_Engine unchanged and SHALL NOT define LLM defaults of its own, so that the Investigation_Engine spec remains the single owner of LLM configuration.
6. THE App_Settings SHALL hold every Secret_Value as a secret-string type whose string representation and repr are masked, so that logging or printing the settings object reveals no Secret_Value.
7. WHEN the documented launch command `python -m backend.api` is run, THE Investigation_API SHALL serve on the HOST and PORT from the App_Settings.

### Requirement 2: Application Startup and Shutdown

**User Story:** As a demo operator, I want the service to start with whatever datasets exist and shut down cleanly, so that a missing dataset or a slow LLM does not block the demo.

#### Acceptance Criteria

1. WHEN the Investigation_API starts, THE Investigation_API SHALL, in this order: create all App_DB tables that do not yet exist, apply the restart recovery of Requirement 18, determine for each Scenario_Registry entry whether it is an Available_Dataset, start the MCP_Client_Manager, and then start the LLM health check without waiting for its result.
2. WHEN the Investigation_API determines Dataset availability, THE Investigation_API SHALL treat a Dataset whose `factory.db` is missing or is not a regular file as unavailable, using filesystem metadata only and without opening the file, SHALL log one warning per unavailable Dataset that names the Dataset_ID and the reason, and SHALL continue starting.
3. THE Investigation_API SHALL NOT generate, regenerate or repair a Dataset during startup.
4. WHEN the Investigation_API starts with DATA_DIR pointing to a missing directory, THE Investigation_API SHALL start and report every Dataset as unavailable.
5. THE Investigation_API SHALL begin accepting HTTP requests within 25 seconds of process start, regardless of whether the LLM health check has completed or any MCP_Session has reached READY.
6. WHILE the Investigation_API is running, THE Investigation_API SHALL refresh the LLM_Status_Cache by running the Investigation_Engine LLM health check every 60 seconds, measured from the completion of the previous check.
7. WHEN the Investigation_API receives a shutdown signal, THE Investigation_API SHALL stop accepting new requests, cancel every Graph_Task, close every MCP_Session, and terminate each Industrial_MCP_Server subprocess, killing any subprocess that has not exited within 5 seconds, so that no Industrial_MCP_Server subprocess remains after the Investigation_API process exits.
8. WHEN the Investigation_API cancels a Graph_Task during shutdown, THE Investigation_API SHALL leave the Case_Status unchanged in the App_DB, so that the restart recovery of Requirement 18 handles the Case on the next start.

### Requirement 3: MCP Client Manager Sessions

**User Story:** As an investigation engine developer, I want a reliable typed MCP client per dataset, so that graph nodes can call factory tools without managing subprocesses.

#### Acceptance Criteria

1. WHEN the MCP_Client_Manager starts, THE MCP_Client_Manager SHALL start one Industrial_MCP_Server subprocess with `python -m industrial_mcp --dataset <dataset_id> --data-dir <DATA_DIR>` and one MCP_Session for each Available_Dataset, with all sessions starting concurrently and each session initialization limited to 20 seconds.
2. THE MCP_Client_Manager SHALL report the MCP_Session_Status NOT_STARTED for a Dataset that is not an Available_Dataset, STARTING while the session initializes, READY after a successful initialization, and FAILED after an initialization or restart that did not succeed.
3. THE MCP_Client_Manager SHALL provide one typed async method for each of the tools get_factory_context, get_eol_summary, get_product_traces, get_equipment_events, get_process_changes, get_reference_sample_checks, get_source_records and run_simulated_verification. Each method SHALL take a Dataset_ID, an optional Case_ID and the tool arguments, and SHALL return the parsed tool result together with its MCP_Call_ID.
4. WHEN a tool returns an MCP_Tool_Error, THE MCP_Client_Manager SHALL raise a typed error carrying the MCP_Tool_Error code, message and MCP_Call_ID, and SHALL NOT restart the session or retry the call.
5. THE MCP_Client_Manager SHALL execute at most one tool call at a time per MCP_Session, queuing concurrent calls for the same Dataset in arrival order, while calls for different Datasets SHALL run concurrently.
6. IF a tool call does not complete within the MCP_Call_Timeout, measured from the moment the call acquires its MCP_Session, THEN THE MCP_Client_Manager SHALL treat the call as a Transport_Failure.
7. WHEN a Transport_Failure occurs during a call of a tool other than run_simulated_verification, THE MCP_Client_Manager SHALL terminate the subprocess, start a new subprocess and MCP_Session, and retry the call exactly once on the new session.
8. WHEN a Transport_Failure occurs during a run_simulated_verification call after the request was written to the session, THE MCP_Client_Manager SHALL restart the session but SHALL NOT retry the call, and SHALL raise an UNAVAILABLE error stating that the verification outcome is unknown, because the server may already have appended verification rows.
9. IF the retry of criterion 7 also fails, or the restart fails, THEN THE MCP_Client_Manager SHALL raise a typed error with code UNAVAILABLE and set the MCP_Session_Status to FAILED.
10. WHEN a call is made for a Dataset whose MCP_Session_Status is FAILED, THE MCP_Client_Manager SHALL attempt one session restart before executing the call, and SHALL raise UNAVAILABLE without executing the call if that restart fails.
11. IF a call is made for a Dataset_ID that is not an Available_Dataset, THEN THE MCP_Client_Manager SHALL raise a typed error with code UNAVAILABLE without starting a subprocess.
12. WHEN the Reset_Function has regenerated a Dataset, THE MCP_Client_Manager SHALL keep the existing MCP_Session for that Dataset, so that the next tool call returns data from the regenerated Factory_DB.

### Requirement 4: MCP Call Recording

**User Story:** As a quality engineer reviewing a case, I want every factory query recorded, so that I can audit what the agent looked at.

#### Acceptance Criteria

1. WHEN the MCP_Client_Manager finishes a tool call attempt, THE MCP_Client_Manager SHALL insert one MCP_Call_Record with id, case_id (null for calls without a Case), dataset_id, tool, arguments (JSON), status, error_code, duration_ms, mcp_call_id, result_size and created_at.
2. THE MCP_Client_Manager SHALL set the MCP_Call_Record status to `OK` for a successful call, `TOOL_ERROR` for an MCP_Tool_Error, `TIMEOUT` for a call that exceeded the MCP_Call_Timeout and `TRANSPORT_ERROR` for any other Transport_Failure.
3. THE MCP_Client_Manager SHALL set error_code to the MCP_Tool_Error code for status `TOOL_ERROR`, to `UNAVAILABLE` for status `TIMEOUT` or `TRANSPORT_ERROR`, and to null for status `OK`.
4. THE MCP_Client_Manager SHALL set result_size to the number of bytes of the UTF-8 JSON serialization of the tool result, or to 0 when the call returned no result.
5. WHEN a call is retried under Requirement 3 criterion 7, THE MCP_Client_Manager SHALL insert one MCP_Call_Record for the failed attempt and one for the retry.
6. THE MCP_Client_Manager SHALL set mcp_call_id to the MCP_Call_ID from the response when the server returned one, and to null otherwise.
7. IF inserting an MCP_Call_Record fails, THEN THE MCP_Client_Manager SHALL log the failure and still return the tool result or raise the tool error to the caller.

### Requirement 5: Application Store

**User Story:** As a backend developer, I want one store for all case data, so that the API, the engine and the verification loop read and write consistent records.

#### Acceptance Criteria

1. THE Store SHALL define these App_DB tables with SQLAlchemy Core: `cases`, `case_events`, `evidence_items`, `hypotheses_snapshots`, `proposals`, `decisions`, `judgment_changes`, `reports`, `mcp_calls`, `llm_calls` and `dataset_epochs`.
2. THE Store SHALL define `cases` with columns case_id (primary key), dataset_id, status, created_at, updated_at, detected_at (nullable), anomaly (JSON, nullable), final_conclusion (JSON, nullable), error (JSON, nullable) and failure_epoch (integer, nullable), and `dataset_epochs` with columns dataset_id (primary key) and epoch (integer).
3. THE Store SHALL define `case_events` with columns case_id, seq, type, payload (JSON) and created_at, with a unique constraint on (case_id, seq).
4. THE Store SHALL define `evidence_items` with a unique (case_id, evidence_id) key and columns for summary, payload (JSON), record_refs (JSON list of Record_Refs) and created_at; `hypotheses_snapshots` with a unique (case_id, round) key and columns hypotheses (JSON) and created_at; `proposals` with a unique (case_id, proposal_id) key and columns round, payload (JSON), status and created_at; `decisions` with columns id, case_id, action, proposal_id (nullable), note (nullable), actor and created_at; and `judgment_changes` with columns id, case_id, round, hypothesis_id, payload (JSON) and created_at.
5. THE Store SHALL define `reports` with columns case_id, version, report (JSON), markdown and created_at, with a unique constraint on (case_id, version), and `llm_calls` with columns id, case_id (nullable), purpose, model, tokens_in, tokens_out, latency_ms, status and created_at.
6. THE Store SHALL declare a foreign key from the case_id column of every table except `mcp_calls` and `llm_calls` to `cases`.case_id, and SHALL declare nullable foreign keys from `mcp_calls`.case_id and `llm_calls`.case_id to `cases`.case_id.
7. THE Store SHALL write every wall-clock timestamp column as a UTC_Timestamp produced with the Time_Util.
8. WHEN the Store opens an App_DB connection, THE Store SHALL enable SQLite foreign key enforcement, WAL journal mode and a busy timeout of at least 5 seconds.
9. WHEN the Store creates a Case, THE Store SHALL assign the next Case_ID in sequence, starting at `CASE-0001`, so that Case_IDs are unique across the App_DB and are never reused after a reset.
10. THE Store SHALL provide repository functions for every write the Investigation_Engine and Verification_Loop need (case status, anomaly, Evidence_Items, Hypothesis_Snapshots, Proposals, Decisions, Judgment_Changes, Reports, LLM_Call_Records), and SHALL execute database work without blocking the asyncio event loop.
11. WHEN the Store saves a Report for a Case, THE Store SHALL assign version 1 to the first Report and the previous highest version plus 1 to each later Report of that Case.
12. THE Store SHALL contain no table or column that stores a Scenario_Label, a World_State_File value or a Ground_Truth_File value.

### Requirement 6: Case Event Log

**User Story:** As a quality engineer, I want an append-only trail of everything that happened in a case, so that I can replay the investigation and trust its history.

#### Acceptance Criteria

1. WHEN the Investigation_Engine or Verification_Loop emits a Progress_Event for a Case, THE Store SHALL persist it as a Case_Event with the Progress_Event type and payload before the Investigation_API delivers it to any Event_Stream subscriber.
2. WHEN a Case_Status changes, THE Store SHALL write the new status to `cases` and append a `status_changed` Case_Event with payload `{from, to, reason}` in the same transaction.
3. WHEN the Store accepts a Decision, THE Store SHALL append a `decision_recorded` Case_Event whose payload contains the action, proposal_id, note and actor.
4. WHEN the Store appends a Case_Event, THE Store SHALL assign Event_Seq equal to the highest existing Event_Seq of that Case plus 1, or 1 for the first event, inside the inserting transaction, so that the Event_Seq values of a Case are unique and contiguous even when events are appended concurrently.
5. THE Store SHALL provide no function that updates or deletes a Case_Event.
6. WHEN the Store persists a Case_Event, THE Store SHALL redact every Secret_Value occurring in the payload to the string `[REDACTED]`.
7. THE Store SHALL persist as Case_Events only the types of the Case_Event_Catalog, each with the payload fields listed there, including `audit` Case_Events with any non-empty `name`, so that audit-trail-only records of the Investigation_Engine and the Verification_Loop are kept as `audit` events; and IF an emitter submits any other type, THEN THE Store SHALL NOT persist it and SHALL log a warning naming the type and the Case_ID.
8. WHEN a Case_Status changes to COMPLETED, FAILED or FAILED_LLM, THE Store SHALL append exactly one `completed` Case_Event with payload `{final_status}` equal to the new status, immediately after the `status_changed` Case_Event of that change and in the same transaction.

### Requirement 7: Error Responses and Request Validation

**User Story:** As a UI developer, I want one predictable error format, so that the UI can show clear messages for every failure.

#### Acceptance Criteria

1. IF a request to any `/api/*` endpoint fails, THEN THE Investigation_API SHALL respond with an Error_Body and the HTTP status for its code: 400 for INVALID_ARGUMENT and the decision validation codes (INVALID_ACTION, ACTION_NOT_OFFERED, UNKNOWN_PROPOSAL, UNEXPECTED_PROPOSAL_ID, NOTE_REQUIRED, NOTE_TOO_LONG, INVALID_ACTOR, REJECT_LIMIT_REACHED), 404 for NOT_FOUND, 409 for CONFLICT and DATASET_CHANGED, 413 for PAYLOAD_TOO_LARGE, 503 for LLM_UNAVAILABLE and DATASET_UNAVAILABLE, and 500 for INTERNAL.
2. WHEN request validation fails (malformed JSON, missing required field, wrong type, unknown field, out-of-range query parameter), THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ARGUMENT, and `details` SHALL list each invalid field location and a message, instead of the FastAPI default 422 response.
3. IF a request targets an undefined route, a Dataset_ID not in the Scenario_Registry, a Case_ID that does not exist or does not match the Case_ID format, or an unknown equipment_id or evidence_id, THEN THE Investigation_API SHALL respond with HTTP 404 and code NOT_FOUND.
4. IF a request targets a Dataset that is in the Scenario_Registry but is not an Available_Dataset, or an MCP call needed by the request fails with code UNAVAILABLE, THEN THE Investigation_API SHALL respond with HTTP 503 and code DATASET_UNAVAILABLE.
5. IF a request body exceeds the Body_Limit, as declared by Content-Length or as counted while reading a body without Content-Length, THEN THE Investigation_API SHALL respond with HTTP 413 and code PAYLOAD_TOO_LARGE without passing the body to the endpoint handler.
6. IF an unexpected exception occurs while handling a request, THEN THE Investigation_API SHALL respond with HTTP 500, code INTERNAL and a generic message, SHALL include no stack trace, exception text, file path or Secret_Value in the response, and SHALL log the stack trace with a request identifier that is also returned in `details.request_id`.
7. THE Investigation_API SHALL validate every request body and query parameter with a Pydantic model that rejects unknown fields.
8. THE Investigation_API SHALL serve OpenAPI documentation at `/api/docs` and the OpenAPI schema at `/api/openapi.json`, and the schema SHALL document the Error_Body responses of each endpoint.

### Requirement 8: Health, LLM Status and Scenario Endpoints

**User Story:** As a demo operator, I want to see which datasets, MCP sessions and the LLM are usable, so that I know which features work before starting an investigation.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/health`, THE Investigation_API SHALL respond with HTTP 200 and a body containing status, version, `datasets` as a list of `{dataset_id, available}` in Scenario_Registry order, and `mcp` as a list of `{dataset_id, session_status}` with the MCP_Session_Status of each Dataset.
2. THE Investigation_API SHALL set the health status to `OK` when every Dataset is an Available_Dataset and every MCP_Session_Status is READY, and to `DEGRADED` otherwise, and SHALL respond to `GET /api/health` without waiting for an LLM check or an MCP call.
3. WHEN a client calls `GET /api/llm/status`, THE Investigation_API SHALL respond with HTTP 200 and the LLM_Status_Cache as `{status, model, provider, checked_at, reason}`, where reason is present only when status is not OK.
4. WHILE no LLM health check has completed since startup, THE Investigation_API SHALL report status UNAVAILABLE, checked_at null and reason `health check pending` from `GET /api/llm/status`.
5. WHEN a client calls `POST /api/llm/status/refresh`, THE Investigation_API SHALL run the LLM health check, update the LLM_Status_Cache, and respond with HTTP 200 and the new status. Concurrent refresh requests SHALL share one running check.
6. THE Investigation_API SHALL return no Secret_Value, API key fragment or provider credential in any LLM status response, and SHALL limit reason to 200 characters.
7. WHEN a client calls `GET /api/scenarios`, THE Investigation_API SHALL respond with HTTP 200 and one entry `{dataset_id, key, label, description, available}` per Scenario_Registry entry in registry order, and SHALL NOT include the default seed or any Ground_Truth_File content.

### Requirement 9: Dataset Reset

**User Story:** As a demo presenter, I want to reset a dataset to its generated state, so that I can rerun a scenario without leftover verification data.

#### Acceptance Criteria

1. WHEN a client calls `POST /api/datasets/{id}/reset` for an Available_Dataset with no Active_Case, THE Investigation_API SHALL call the Reset_Function for that Dataset_ID and respond with HTTP 200 and a summary `{dataset_id, reset_at, data_time_range: {start, end}, counts: {products, eol_tests, reference_sample_checks, verification_eol_tests, verification_reference_checks}}` obtained after the reset through the MCP_Client_Manager: data_time_range and the verification counts from get_factory_context, products as the product count from the get_factory_context record counts, eol_tests as the first historical EOL test count from get_eol_summary over the Data_Time_Range, and reference_sample_checks as the historical count from get_reference_sample_checks for each EOL_Tester.
2. WHEN a reset has completed, THE Investigation_API SHALL report zero verification-origin `eol_tests` and `reference_sample_checks` rows in the reset summary, and the next MCP tool call for that Dataset SHALL return data from the regenerated Factory_DB.
3. IF the Dataset has an Active_Case, THEN THE Investigation_API SHALL respond with HTTP 409 and code CONFLICT, with `details.case_id` naming the Active_Case, and SHALL NOT call the Reset_Function.
4. IF the Dataset is not an Available_Dataset, THEN THE Investigation_API SHALL respond with HTTP 503 and code DATASET_UNAVAILABLE and SHALL NOT call the Reset_Function.
5. WHILE a reset of a Dataset is in progress, THE Investigation_API SHALL respond to `POST /api/cases` and to a second reset for the same Dataset with HTTP 409 and code CONFLICT.
6. IF the Reset_Function raises an error, THEN THE Investigation_API SHALL respond with HTTP 500 and code INTERNAL, and the Dataset SHALL remain in the state it had before the request, as guaranteed by the atomic Reset_Function.
7. WHEN a reset completes, THE Investigation_API SHALL keep all existing Cases and their records in the App_DB unchanged.
8. THE Investigation_API SHALL perform the reset only through the Reset_Function, SHALL NOT write or read the Ground_Truth_File, and SHALL import no module that writes or reads the Ground_Truth_File.
9. WHEN a reset completes successfully, THE Investigation_API SHALL increment the Dataset_Epoch of that Dataset before responding.

### Requirement 10: Dataset Overview

**User Story:** As a line supervisor, I want a factory overview with equipment colors and FAIL rates, so that I can see where an investigation is needed.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/datasets/{id}/overview` for an Available_Dataset, THE Investigation_API SHALL respond with HTTP 200 and a body containing dataset_id, `mode` equal to the string `SIMULATION`, topology, equipment, fail_rates, overall_fail_rate, recent_anomalies and data_time_range `{start, end}`.
2. THE Investigation_API SHALL return topology containing the Stations in line order ST-10, ST-20, ST-30, EOL, the equipment units of each Station, and the two EOL_Tester branches EOL-A and EOL-B as parallel branches after ST-30.
3. THE Investigation_API SHALL return `equipment` as one entry per equipment unit with equipment_id, station_id, name, status (Equipment_Status) and reasons (list of Status_Reason) computed by the rules of Requirement 12.
4. THE Investigation_API SHALL return fail_rates as one entry per EOL_Tester with `recent` and `full_range` objects, each containing tests, fails and fail_rate, where recent covers the Recent_Window and full_range covers the Data_Time_Range.
5. THE Investigation_API SHALL return overall_fail_rate as `{tests, fails, fail_rate}` over all first historical EOL tests in the Data_Time_Range.
6. THE Investigation_API SHALL return recent_anomalies as the list of EOL_Testers flagged by the Anomaly_Detector applied to get_eol_summary results obtained through the MCP_Client_Manager, each with tester_id, baseline and comparison `{tests, fails, fail_rate}`, ratio and p_value, and an empty list when no EOL_Tester is flagged.
7. WHEN the same Factory_DB content is queried twice, THE Investigation_API SHALL return identical Overview bodies.
8. THE Investigation_API SHALL compute the Overview without any LLM call, so that the Overview works when the LLM_Health_Status is UNAVAILABLE or MISCONFIGURED.
9. IF the Dataset is in the Scenario_Registry but is not an Available_Dataset, THEN THE Investigation_API SHALL respond with HTTP 503 and code DATASET_UNAVAILABLE.
10. THE Investigation_API SHALL obtain all Factory_DB data for the Overview, equipment detail and trends endpoints only through the MCP_Client_Manager, using the tools get_factory_context, get_eol_summary, get_equipment_events, get_process_changes and get_reference_sample_checks, SHALL record each of these calls as an MCP_Call_Record with case_id null, and SHALL count none of them against any Case_Budget.
11. THE Investigation_API SHALL NOT open the Factory_DB, the World_State_File or the Ground_Truth_File to compute the Overview, equipment detail or trends.

### Requirement 11: Equipment Detail and Trends

**User Story:** As a quality engineer, I want equipment drill-downs and time trends, so that I can inspect signals behind an equipment color.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/datasets/{id}/equipment/{equipment_id}` for an EOL_Tester, THE Investigation_API SHALL respond with HTTP 200 and fail_rate_buckets (one `{bucket_start, tests, fails, fail_rate}` per 30-minute Bucket), by_model (one `{model_id, tests, fails, fail_rate}` per product model), recent_failures (at most 20 FAIL first tests, newest first, each with test_id, sn, ts, model_id and failure_code) and reference_checks (every Reference_Sample_Check of that EOL_Tester ordered by ts, each with check_id, ts, sample_id, nominal, measured, deviation, result and origin).
2. WHEN a client calls the equipment detail endpoint for the ST-20 equipment unit, THE Investigation_API SHALL respond with HTTP 200 and parameter_stats (for each program_version, each parameter angle and torque, and each 30-minute Bucket: n, mean, p5 and p95) and process_changes (every `process_changes` row of ST-20 ordered by ts).
3. WHEN a client calls the equipment detail endpoint for the ST-10 or ST-30 equipment unit, THE Investigation_API SHALL respond with HTTP 200 and step_counts (one `{bucket_start, steps, by_result}` per 30-minute Bucket) and the total step count, taken from the `step_counts` (step_count, by_result) and `step_total_count` of the get_equipment_events result for that equipment, called with `bucket_minutes` 30 through the MCP_Client_Manager.
4. THE Investigation_API SHALL include in every equipment detail response the equipment_id, station_id, status and reasons from Requirement 12, and the `equipment_events` rows of that equipment ordered by ts.
5. IF the equipment_id is not an equipment unit in the Factory_DB, THEN THE Investigation_API SHALL respond with HTTP 404 and code NOT_FOUND.
6. WHEN a client calls `GET /api/datasets/{id}/trends`, THE Investigation_API SHALL respond with HTTP 200 and buckets of `bucket_minutes` minutes (default 30) containing: per EOL_Tester `{tests, fails, fail_rate}` per Bucket; ST-20 angle and torque `{n, mean, p5, p95}` per Bucket; reference_deviations per EOL_Tester as a list of `{ts, deviation, result, origin}`; and process_change markers `{ts, equipment_id, change_type, old_value, new_value}`.
7. IF bucket_minutes is not an integer from 15 to 240 inclusive, THEN THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ARGUMENT.
8. THE Investigation_API SHALL report fail_rate, mean, p5 and p95 as null for a Bucket with no data, SHALL compute p5 and p95 with linear interpolation between closest ranks, and SHALL emit every Bucket of the Data_Time_Range, including empty ones, in ascending order.
9. THE Investigation_API SHALL compute equipment detail and trends without any LLM call and only from Factory_DB data obtained through the MCP_Client_Manager as defined in Requirement 10 criterion 10.

### Requirement 12: Deterministic Equipment Status Rules

**User Story:** As a line supervisor, I want equipment colors computed by fixed, explainable rules, so that the dashboard shows signals without claiming root causes.

#### Acceptance Criteria

1. THE Investigation_API SHALL set the Equipment_Status of an EOL_Tester to RED with Status_Reason code `TESTER_ANOMALY_FLAGGED` when the Anomaly_Detector flags that EOL_Tester.
2. THE Investigation_API SHALL set the Equipment_Status of the ST-20 equipment to RED with Status_Reason code `PARAMETER_SHIFT_AFTER_PROGRAM_CHANGE` when a program-version `process_changes` row exists for ST-20 and a two-sample Kolmogorov–Smirnov test between the angle values, or between the torque values, recorded with the change's old_value and with its new_value has a p-value below 0.01, where each side has at least 30 values. The Investigation_API SHALL obtain the raw angle and torque values for this test from get_equipment_events for the ST-20 equipment over the Data_Time_Range with `include_measurements` true, called through the MCP_Client_Manager.
3. WHEN no RED rule applies, THE Investigation_API SHALL set the Equipment_Status to ORANGE when one or more of the following holds: an `equipment_events` row with event_type `alarm` for that equipment lies in the Recent_Window (code `RECENT_ALARM`); for an EOL_Tester, a historical Reference_Sample_Check of that EOL_Tester has result FAIL (code `REFERENCE_CHECK_FAIL`); for an EOL_Tester, the Recent_Window has at least 20 first historical tests and at least 3 FAIL results and its FAIL_Rate is at least 2.0 times the Baseline_Window FAIL_Rate (code `FAIL_RATE_ELEVATED`).
4. WHEN no RED or ORANGE rule applies and the Factory_DB contains at least one `process_steps` row (for ST-10, ST-20, ST-30) or one historical first `eol_tests` row (for an EOL_Tester) of that equipment, THE Investigation_API SHALL set the Equipment_Status to GREEN with an empty reasons list.
5. WHEN the Factory_DB contains no rows of that equipment as defined in criterion 4, THE Investigation_API SHALL set the Equipment_Status to GREY with Status_Reason code `NO_DATA`.
6. WHEN more than one rule applies, THE Investigation_API SHALL report the highest color in the order RED > ORANGE > GREEN and SHALL list a Status_Reason for every applied RED and ORANGE rule.
7. THE Investigation_API SHALL write Status_Reason messages that state only the observed signal and its numbers (for example counts, rates, ratio, p-value, change values), and SHALL NOT include a Conclusion_Category value or a root-cause statement.
8. THE Investigation_API SHALL define the thresholds of criteria 1 to 3 (0.01, 2.0, 30, 20, 3, 60 minutes, 2 hours) as named constants in one module.
9. WHEN the overview is computed on Datasets generated with their Scenario_Registry default seeds, THE Investigation_API SHALL report: for `ds-00`, all five equipment units GREEN; for `ds-01`, EOL-B RED and ST-20 not RED; for `ds-02`, ST-20 RED; for `ds-03`, EOL-B RED and ST-20 not RED.

### Requirement 13: Case Creation

**User Story:** As a quality engineer, I want to start an investigation on a dataset with one click, so that the agent begins working on the detected anomaly.

#### Acceptance Criteria

1. WHEN a client calls `POST /api/cases` with body `{dataset_id}` for an Available_Dataset with no Active_Case and the LLM_Health_Status is OK, THE Investigation_API SHALL create a Case with status CREATED, start a Graph_Task for it, and respond with HTTP 201, a Location header `/api/cases/<case_id>` and a body containing case_id, dataset_id, status and created_at.
2. WHEN the LLM_Status_Cache is older than 60 seconds or no check has completed, THE Investigation_API SHALL run a fresh LLM health check before deciding on a `POST /api/cases` request.
3. IF the LLM_Health_Status is not OK, THEN THE Investigation_API SHALL respond with HTTP 503 and code LLM_UNAVAILABLE, with `details.llm_status` set to UNAVAILABLE or MISCONFIGURED and `details.reason` set to the sanitized reason, and SHALL create no Case.
4. IF the Dataset is not an Available_Dataset or its MCP_Session_Status is FAILED after one restart attempt, THEN THE Investigation_API SHALL respond with HTTP 503 and code DATASET_UNAVAILABLE and SHALL create no Case.
5. IF the Dataset already has an Active_Case, THEN THE Investigation_API SHALL respond with HTTP 409 and code CONFLICT, with `details.case_id` naming the Active_Case.
6. WHEN several `POST /api/cases` requests for the same Dataset arrive concurrently, THE Investigation_API SHALL serialize them per Dataset so that exactly one request creates a Case and every other request receives HTTP 409.
7. THE Investigation_API SHALL accept only the field dataset_id in the `POST /api/cases` body and SHALL reject any other field with HTTP 400 and code INVALID_ARGUMENT, so that no user free text reaches the LLM through case creation.
8. WHEN the Graph_Task starts, THE Investigation_API SHALL call the Investigation_Engine entrypoint with the Case_ID and Dataset_ID only, and SHALL NOT pass the Scenario_Label, Scenario_Key or any Scenario_Registry field other than the Dataset_ID.
9. IF a Graph_Task raises an exception that the Investigation_Engine or Verification_Loop did not convert into a Case_Status, THEN THE Investigation_API SHALL set the Case_Status to FAILED with error `{code: "INTERNAL", message}` where message contains no stack trace or Secret_Value, and SHALL log the stack trace.
10. THE Investigation_API SHALL allow Cases on different Datasets to run concurrently.
11. WHEN the Investigation_API creates a Case, THE Investigation_API SHALL increment the Dataset_Epoch of the Case's Dataset in the same transaction that inserts the Case.

### Requirement 14: Case Listing and Case Detail

**User Story:** As a quality engineer, I want to see my cases and the full state of one case, so that I can follow evidence, hypotheses and decisions.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/cases`, THE Investigation_API SHALL respond with HTTP 200 and at most 50 Case summaries ordered by created_at descending and then Case_ID descending, each with case_id, dataset_id, status, created_at, updated_at, detected_at and report_available.
2. WHEN the query parameter dataset_id is given, THE Investigation_API SHALL return only Cases of that Dataset, and IF the value is not a Scenario_Registry Dataset_ID, THEN THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ARGUMENT.
3. WHEN a client calls `GET /api/cases/{id}` for an existing Case, THE Investigation_API SHALL respond with HTTP 200 and case_id, dataset_id, status, created_at, updated_at, detected_at, anomaly, evidence (list of Evidence_Items with evidence_id, summary and record_refs), current_hypotheses (the latest Hypothesis_Snapshot or an empty list), rounds (number of Hypothesis_Snapshots), pending_proposals, decisions (all Decisions in creation order), judgment_changes (all Judgment_Changes in creation order), budgets `{mcp_calls, llm_calls, verification_rounds, reject_all}` with each entry `{used, limit, remaining}` and the limits 20, 40, 3 and 2 of the Case_Budget, final_conclusion, error, report `{available, version, created_at}`, and last_event_seq (the highest persisted Event_Seq of the Case, or 0 when the Case has no Case_Event).
4. THE Investigation_API SHALL return the open Proposals of the current round in pending_proposals while the Case_Status is AWAITING_APPROVAL, and an empty list in every other Case_Status.
5. THE Investigation_API SHALL return final_conclusion as null until the Verification_Loop has stored a final conclusion, and report.available as false with version and created_at null until a Report exists.
6. THE Investigation_API SHALL include no Scenario_Label, Scenario_Key, World_State_File value or Ground_Truth_File value in Case responses.
7. THE Investigation_API SHALL read the Case detail and its last_event_seq in one App_DB read transaction, so that every Case_Event with Event_Seq up to last_event_seq is reflected in the response and a client can resume the Event_Stream with `after` equal to last_event_seq without a gap or duplicate.

### Requirement 15: Case Event Stream

**User Story:** As a UI developer, I want a resumable live stream of case events, so that the workspace updates in real time and recovers after a dropped connection.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/cases/{id}/events` for an existing Case, THE Investigation_API SHALL respond with HTTP 200, Content-Type `text/event-stream`, header `Cache-Control: no-cache` and header `X-Accel-Buffering: no`.
2. THE Investigation_API SHALL send each Case_Event as one SSE message with `id` equal to the Event_Seq, `event` equal to the Case_Event type and `data` equal to a single-line JSON object containing case_id, seq, type, payload and created_at.
3. WHEN the request carries a `Last-Event-ID` header or an `after` query parameter, THE Investigation_API SHALL first send every stored Case_Event of that Case with Event_Seq greater than the given value in ascending order, and then send new Case_Events as they are appended. The `Last-Event-ID` header SHALL take precedence over `after`. Without either, replay SHALL start from Event_Seq 1.
4. THE Investigation_API SHALL deliver every Case_Event with Event_Seq greater than the requested value exactly once and in ascending Event_Seq order, with no gap between the replayed and the live events.
5. IF `Last-Event-ID` or `after` is not a non-negative integer, THEN THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ARGUMENT.
6. WHILE an Event_Stream is open, THE Investigation_API SHALL send an SSE comment line (`: ping`) when no message has been sent for 15 seconds.
7. WHEN the Investigation_API has sent a `completed` Case_Event that is the latest Case_Event of the Case, THE Investigation_API SHALL close the Event_Stream after that event. A `completed` Case_Event replayed from before a retry SHALL NOT close the Event_Stream. WHEN the Case already has a Terminal_Status at connection time, THE Investigation_API SHALL send the replay and then close the Event_Stream.
8. WHILE the Case_Status is AWAITING_APPROVAL, THE Investigation_API SHALL keep the Event_Stream open, and THE Investigation_API SHALL NOT close the Event_Stream on a `status_changed` Case_Event.
9. WHEN a client disconnects, THE Investigation_API SHALL release the subscription within 30 seconds without affecting the Graph_Task.
10. THE Investigation_API SHALL support at least 10 concurrent Event_Stream subscribers per Case.

### Requirement 16: Human Decision Submission

**User Story:** As a quality engineer, I want to approve, reject or conclude at the approval point, so that no verification runs without my consent.

#### Acceptance Criteria

1. WHEN a client calls `POST /api/cases/{id}/decision` with body `{action, proposal_id?, note?, actor?}` for a Case in status AWAITING_APPROVAL and the Decision is valid, THE Investigation_API SHALL store the Decision, resume the graph from its Checkpoint in a Graph_Task with that Decision, and respond with HTTP 202 and `{case_id, status, decision_id}`.
2. IF the Case_Status is not AWAITING_APPROVAL, THEN THE Investigation_API SHALL respond with HTTP 409 and code CONFLICT, with `details.status` set to the current Case_Status.
3. IF action is not `approve`, `reject_all` or `conclude`, THEN THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ACTION.
4. IF action is `approve` and proposal_id is missing or does not identify a currently pending Proposal of the Case, THEN THE Investigation_API SHALL respond with HTTP 400 and code UNKNOWN_PROPOSAL; IF action is `reject_all` or `conclude` and proposal_id is present, THEN THE Investigation_API SHALL respond with HTTP 400 and code UNEXPECTED_PROPOSAL_ID.
5. IF action is `reject_all` and note is missing or empty after trimming whitespace, THEN THE Investigation_API SHALL respond with HTTP 400 and code NOTE_REQUIRED; IF a given note is longer than 500 characters for any action, THEN THE Investigation_API SHALL respond with HTTP 400 and code NOTE_TOO_LONG; IF a given actor is empty or longer than 64 characters, THEN THE Investigation_API SHALL respond with HTTP 400 and code INVALID_ACTOR. These codes are the Verification_Loop decision validation codes, returned unchanged in `error.code`.
6. IF action is `reject_all` and the Case already has two `reject_all` Decisions, THEN THE Investigation_API SHALL respond with HTTP 400 and code REJECT_LIMIT_REACHED, and SHALL store no Decision; IF the action is not among the actions offered in the pending approval request (for example `approve` when only conclude is offered), THEN THE Investigation_API SHALL respond with HTTP 400 and code ACTION_NOT_OFFERED, and SHALL store no Decision.
7. THE Investigation_API SHALL accept note as optional for `approve` and `conclude`, SHALL accept actor as an optional string of 1 to 64 characters for every action, and SHALL set actor to `engineer` when it is omitted.
8. WHEN a Decision is accepted, THE Investigation_API SHALL change the Case_Status from AWAITING_APPROVAL to RUNNING for `approve` and `reject_all`, or to CONCLUDING for `conclude`, in the same transaction that stores the Decision and before responding, so that a second concurrent Decision for the same Case receives HTTP 409.
9. THE Investigation_API SHALL validate the request in this order: Case existence (404), body schema (400), Case_Status (409), Decision rules of criteria 4 to 6 (400).
10. THE Investigation_API SHALL execute a verification only through the graph after an `approve` Decision, and SHALL expose no endpoint that calls run_simulated_verification directly.

### Requirement 17: Evidence, Report and MCP Call Retrieval

**User Story:** As a quality engineer, I want to open the raw records behind evidence, download the report and audit tool calls, so that every conclusion can be traced to source data.

#### Acceptance Criteria

1. WHEN a client calls `GET /api/cases/{id}/evidence/{evidence_id}` for an existing Evidence_Item, THE Investigation_API SHALL respond with HTTP 200 and the Evidence_Item fields plus source_records resolved by calling get_source_records for the first 50 Record_Refs in record_refs order, and `truncated` set to true when the Evidence_Item has more than 50 Record_Refs.
2. THE Investigation_API SHALL record the get_source_records call of criterion 1 as an MCP_Call_Record with the Case_ID.
3. IF the get_source_records call fails, THEN THE Investigation_API SHALL still respond with HTTP 200 and the Evidence_Item, with source_records set to null and source_records_error set to `{code, message}`.
4. IF the evidence_id does not belong to the Case, THEN THE Investigation_API SHALL respond with HTTP 404 and code NOT_FOUND.
5. WHEN a client calls `GET /api/cases/{id}/report`, THE Investigation_API SHALL respond with HTTP 200 and `{case_id, version, created_at, report}` for the highest Report version, and IF no Report exists, THEN THE Investigation_API SHALL respond with HTTP 404 and code NOT_FOUND.
6. WHEN a client calls `GET /api/cases/{id}/report.md`, THE Investigation_API SHALL respond with HTTP 200, Content-Type `text/markdown; charset=utf-8`, header `Content-Disposition: attachment; filename="<case_id>-report.md"` and a body byte-identical to the stored markdown of the highest Report version, and IF no Report exists, THEN THE Investigation_API SHALL respond with HTTP 404 and code NOT_FOUND.
7. WHEN a client calls `GET /api/cases/{id}/mcp-calls`, THE Investigation_API SHALL respond with HTTP 200 and the MCP_Call_Records of that Case ordered by created_at and then id ascending, at most 1,000 records, with `truncated` set to true when more exist.

### Requirement 18: Case Retry, Concurrency and Restart Recovery

**User Story:** As a demo operator, I want failed or interrupted cases to recover predictably, so that an LLM outage or server restart does not lose an investigation.

#### Acceptance Criteria

1. WHEN a client calls `POST /api/cases/{id}/retry` for a Case in status FAILED_LLM that has a Checkpoint, whose failure_epoch equals the current Dataset_Epoch of its Dataset, while the Dataset has no other Active_Case and the LLM_Health_Status is OK, THE Investigation_API SHALL set the Case_Status to RUNNING, resume the graph from the Checkpoint in a Graph_Task, and respond with HTTP 202 and `{case_id, status}`.
2. IF the Case_Status is not FAILED_LLM or the Case has no Checkpoint, THEN THE Investigation_API SHALL respond with HTTP 409 and code CONFLICT with a `details.reason` naming the condition.
3. IF the LLM_Health_Status is not OK after the freshness check of Requirement 13 criterion 2, THEN THE Investigation_API SHALL respond to a retry with HTTP 503 and code LLM_UNAVAILABLE and leave the Case_Status FAILED_LLM.
4. THE Investigation_API SHALL allow at most one Active_Case per Dataset at any time, across case creation, retry and Decision handling.
5. WHEN the Investigation_API starts and finds Cases in status CREATED, RUNNING or CONCLUDING, THE Investigation_API SHALL set each Case that has a Checkpoint to FAILED_LLM and each Case without a Checkpoint to FAILED, with reason `server restarted`, and SHALL append a `status_changed` Case_Event for each.
6. WHEN the Investigation_API starts and finds Cases in status AWAITING_APPROVAL, THE Investigation_API SHALL leave them unchanged, so that a Decision submitted after the restart resumes the graph from the Checkpoint.
7. WHEN the LLM_Health_Status is not OK, THE Investigation_API SHALL keep serving health, LLM status, scenarios, reset, overview, equipment detail, trends, case listing, case detail, events, evidence, report and MCP call endpoints.
8. WHEN a Case_Status changes to FAILED_LLM, including through the restart recovery of criterion 5, THE Store SHALL set the failure_epoch of the Case to the current Dataset_Epoch of its Dataset in the same transaction.
9. IF the failure_epoch of a FAILED_LLM Case differs from the current Dataset_Epoch of its Dataset, THEN THE Investigation_API SHALL respond to a retry with HTTP 409 and code DATASET_CHANGED, with a message stating that the Dataset was reset or another Case was created since the failure, and SHALL leave the Case_Status FAILED_LLM.
10. IF another Active_Case exists on the same Dataset, THEN THE Investigation_API SHALL respond to a retry with HTTP 409 and code CONFLICT, with `details.case_id` naming that Active_Case, and SHALL leave the Case_Status FAILED_LLM.
11. THE Investigation_API SHALL validate a retry request in this order: Case existence (404), Case_Status and Checkpoint (criterion 2, 409 CONFLICT), Dataset_Epoch (criterion 9, 409 DATASET_CHANGED), other Active_Case (criterion 10, 409 CONFLICT), LLM_Health_Status (criterion 3, 503), and SHALL perform these checks and the status change under the per-Dataset serialization of Requirement 13 criterion 6.

### Requirement 19: Security and Boundary Controls

**User Story:** As a project owner, I want the local demo to have tight boundaries, so that secrets, hidden truth and real equipment stay out of reach.

#### Acceptance Criteria

1. THE Investigation_API SHALL bind to HOST `127.0.0.1` unless the HOST setting is explicitly overridden, which the Docker Compose configuration does with `0.0.0.0`.
2. THE Investigation_API SHALL send CORS headers only for request origins listed in CORS_ORIGINS, allowing methods GET and POST, the header Content-Type and Last-Event-ID, and no credentials.
3. THE Investigation_API SHALL include no Secret_Value in any HTTP response, log line, Case_Event, MCP_Call_Record or LLM_Call_Record.
4. THE Investigation_API SHALL import no module that reads or writes the Ground_Truth_File, enforced by an import-linter contract covering the `backend` package, and no `backend` module SHALL open a file named `factory.db`, `world_state.json` or `ground_truth.json`, enforced by a static check over the `backend` package. The Reset_Function of the Simulator is the only code called by the Investigation_API that writes the Factory_DB and the World_State_File.
5. THE Investigation_API SHALL pass only Dataset_IDs and Case_IDs to the Investigation_Engine and Verification_Loop entrypoints, and SHALL NOT pass any Scenario_Label to them.
6. THE Investigation_API SHALL read and modify data only in the App_DB and the Checkpoint_DB, SHALL read Factory_DB data only through the MCP_Client_Manager, SHALL modify Datasets under DATA_DIR only through the Reset_Function, and SHALL expose no endpoint that connects to real equipment or external factory systems.
7. THE Investigation_API SHALL document in the OpenAPI description and the project README that it has no authentication and is intended only for a local demo.

### Requirement 20: Test Coverage

**User Story:** As a developer, I want integration tests with real MCP subprocesses and an opt-in real-LLM test, so that the API contract is verified end to end.

#### Acceptance Criteria

1. THE Investigation_API test suite SHALL run integration tests without an LLM against Datasets generated into a temporary DATA_DIR with registry default seeds, using real Industrial_MCP_Server subprocesses started by the MCP_Client_Manager.
2. THE Investigation_API test suite SHALL include integration tests that verify: the `GET /api/health` and `GET /api/scenarios` bodies; the Equipment_Status expectations of Requirement 12 criterion 9 for all four Datasets; the trends response shape for bucket_minutes 15, 30 and 240 and the 400 response for 14 and 241; equipment detail for an EOL_Tester, ST-20 and ST-10, and 404 for an unknown equipment_id; and that every dashboard request is served through MCP_Call_Records with case_id null.
3. THE Investigation_API test suite SHALL include integration tests that verify that a reset removes all verification-origin rows appended before the reset, and that a reset returns HTTP 409 while a store-seeded Active_Case exists on the Dataset.
4. THE Investigation_API test suite SHALL include integration tests that verify that `POST /api/cases` returns HTTP 503 with code LLM_UNAVAILABLE and `details.llm_status` MISCONFIGURED when the LLM API key setting is empty, and that no Case is created.
5. THE Investigation_API test suite SHALL include integration tests that verify Event_Stream replay on a store-seeded Case: full replay, replay after `?after=<n>`, replay after `Last-Event-ID`, precedence of `Last-Event-ID` over `after`, the SSE headers of Requirement 15 criterion 1, stream closure after a `completed` event, an open stream while the Case is AWAITING_APPROVAL, and a `last_event_seq` in the Case detail equal to the highest replayed Event_Seq.
6. THE Investigation_API test suite SHALL include integration tests that verify the Error_Body format and HTTP status for 400, 404, 409, 413 and 503 responses, including a request body of 65,537 bytes returning 413, and that no response contains a stack trace.
7. THE Investigation_API test suite SHALL include integration tests that verify, with a stubbed Investigation_Engine entrypoint, that case creation passes only the Case_ID and Dataset_ID and that no Scenario_Label text appears in the call arguments or in the App_DB.
8. THE Investigation_API test suite SHALL include integration tests that verify restart recovery: a store-seeded RUNNING Case with a Checkpoint becomes FAILED_LLM, one without a Checkpoint becomes FAILED, and an AWAITING_APPROVAL Case is unchanged, and a retry of a store-seeded FAILED_LLM Case returns HTTP 409 with code DATASET_CHANGED after a reset of its Dataset or after another Case was created on it.
9. THE Investigation_API test suite SHALL include one test marked with pytest marker `llm` that, on `ds-01` with a real LLM, creates a Case, reads the Event_Stream until a `status_changed` event to AWAITING_APPROVAL, approves a pending Proposal, continues through further approval points by approving or concluding until a `completed` event, and then downloads `report.md` with HTTP 200 and the attachment header of Requirement 17 criterion 6.
10. THE Investigation_API test suite SHALL skip tests marked `llm` by default and run them only when the `llm` marker is selected explicitly.
