# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent investigates End-of-Line (EOL) quality anomalies in the fictional Factory Alpha (Line A, stations ST-10, ST-20 and ST-30, EOL_Testers EOL-A and EOL-B, product models Model A and Model B) through the Industrial MCP Server over simulated MES, PPM and EOL data. This spec covers the investigation engine: the part of the backend that detects an anomaly, collects and analyzes evidence, and generates evidence-cited hypotheses before the first verification is proposed.

The spec covers five backend packages and one graph segment:
- `backend/llm`: the LLM provider layer (configuration, health check, structured output, tool calling, secret redaction).
- `backend/analytics`: deterministic statistics over MCP tool outputs (anomaly detection, analyzers, timeline builder).
- `backend/evidence`: the Evidence_Registry and the Citation_Validator.
- The Hypothesis model and the Support_Guardrail (LLM-generated content, enforced by code).
- `backend/agent`: the first segment of the LangGraph Investigation_Graph, from `load_case` to the hand-off to `propose_verification`, with budgets, checkpointing and Progress_Events.

The investigation follows three methodology rules: Is/Is-Not comparison (where the problem is and where it is not), stratification (split by product model and other factors before blaming equipment) and "rule out the measurement system first" (MSA-first).

Out of scope: multi-agent orchestration, retrieval-augmented generation, vector databases, knowledge graphs, verification proposal and execution, human approval, hypothesis updates after verification, conclusion finalization, report generation, HTTP endpoints, SSE transport, and the Store implementation. There is no fallback, demo or rule-based mode: when the LLM is unavailable, an investigation cannot start, and no canned text is ever presented as model output.

Assumptions:
- The `get_factory_context` tool reports the list of EOL_Testers, the list of product models, the ST-20 equipment identifier and the Data_Range (earliest and latest first historical EOL test ts of the Dataset).
- The `get_eol_summary` tool accepts a start and end UTC_Timestamp and a time bucket width in minutes, and reports test counts and FAIL counts (first historical tests only) by tester, by model and by tester × model, per time bucket, a failed SN sample of at most 50 FAIL first historical tests, each with sn, test_id, tester_id, model_id and ts, and a retest summary.
- The `get_equipment_events` tool reports, when `include_measurements` is true, raw ST-20 measurements with meas_id, sn, ts, parameter, value and program_version, up to 2,000 measurements, and states whether the result was truncated.
- MCP tool outputs include the primary-key identifiers of the records they summarize, so that Record_Refs can be built from them.
- FAIL_Rate by program_version is attributed by EOL test time (a time bucket belongs to the program_version active at its start), because no MCP tool joins EOL results to ST-20 program versions for all SNs. The finding states this attribution method in its data.
- Material lot comparison is descriptive: product traces exist only for a sample of failed SNs, so no pass-population baseline is available and no significance test is run.
- Timeline source systems are fixed: process changes → MES, equipment events → PPM, Reference_Sample_Checks → EOL, Anomaly_Onset → ANALYTICS, verification results → VERIFICATION.
- The Case_Status model (CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM and FAILED) and its legal transitions are defined by the verification-loop spec. The active statuses, which block a new Case and a Dataset reset, are CREATED, RUNNING, AWAITING_APPROVAL and CONCLUDING; FAILED_LLM is not active. This spec sets RUNNING, FAILED_LLM and FAILED through that model but does not define the full case lifecycle.
- The Case record, the Store and the Case_Event_Catalog are defined by the investigation-api spec.
- The Detected_Anomaly_Window is the Detection_Window used by the Anomaly_Detector. It is derived from observable data only and is distinct from the hidden Anomaly_Window of the Ground_Truth.
- Checkpoints are written to a SQLite file separate from `app.db`, configured by CHECKPOINT_DB_PATH.
- An LLM call is one logical completion request. Transport retries of the same request count as one LLM call.

Dependencies on other specs:
- virtual-factory-simulator: the shared enums Conclusion_Category and Support_Level in the Factory_Data_Package, the Datasets `ds-00` to `ds-03`, and (for tests only) the Ground_Truth and Scenario_Registry.
- industrial-mcp-server: the tool set, the MCP_Call_ID on every response, the structured error codes (INVALID_ARGUMENT, NOT_FOUND, UNAVAILABLE, LIMIT_EXCEEDED, INTERNAL), the result limits and `get_source_records`.
- investigation-api: the Store (`app.db`), the Case record, the Case_Event_Catalog, the MCP_Client_Manager (one stdio session per Dataset, records every call with case_id), the SSE stream that consumes Progress_Events, the periodic health refresh (every 60 s) and the retry endpoint that resumes a FAILED_LLM case.
- verification-loop: the Case_Status model and its transitions, and the nodes `propose_verification`, `human_approval`, `execute_verification`, `update_hypotheses`, `finalize_conclusion` and `generate_report`, which attach to this graph segment, create Evidence_Items of kind verification, and reuse the Citation_Validator, Support_Guardrail, Context_Builder and the shared Case_Budgets.

## Glossary

- **Investigation_Engine**: The backend component specified here, consisting of the LLM_Provider_Layer, the Analytics_Module, the Evidence_Registry, the Citation_Validator, the Hypothesis_Generator, the Support_Guardrail, the Context_Builder and the Investigation_Graph segment.
- **LLM_Provider_Layer**: The package `backend/llm` that wraps LiteLLM and contains the LLM_Settings, the LLM_Client, the LLM_Health_Check, the Structured_Output_Caller, the Tool_Adapter and the Redactor.
- **LLM_Settings**: The pydantic-settings model that loads LLM_MODEL, LLM_PROVIDER, LLM_API_KEY, LLM_BASE_URL, LLM_THINKING, LLM_TIMEOUT_S and LLM_MAX_RETRIES from environment variables.
- **Effective_Model**: The LiteLLM model string sent with every completion, derived from LLM_MODEL and LLM_PROVIDER.
- **Provider_Prefix**: The part of the Effective_Model before the first `/`, for example `deepseek`, `openai`, `gemini`, `dashscope`, `openrouter` or `ollama`.
- **Thinking_Option_Table**: A table in the LLM_Provider_Layer that maps a Provider_Prefix to the request option that disables model thinking for that provider.
- **No_Key_Provider_Set**: The set of Provider_Prefixes that need no API key; it contains `ollama`.
- **LLM_Client**: The LLM_Provider_Layer component that sends completion requests through LiteLLM, applies transport retries and records LLM_Call_Records.
- **LLM_Call**: One logical completion request sent by the LLM_Client on behalf of a Case, including all its transport retries.
- **LLM_Call_Record**: The audit record of one LLM_Call: case_id, call sequence number, purpose, Effective_Model, token usage, latency, transport attempt count, outcome, and truncated prompt and response text.
- **LLM_Health_Check**: The LLM_Provider_Layer component that determines and caches the Health_Result.
- **Health_Result**: The cached health record with fields status (OK, UNAVAILABLE or MISCONFIGURED), reason (sanitized text), effective_model and checked_at (UTC_Timestamp).
- **Redactor**: The LLM_Provider_Layer function that replaces the configured API key and every Key_Like_String in a text with `[REDACTED]`.
- **Key_Like_String**: A substring that matches one of these patterns: `sk-` followed by 8 or more characters from `[A-Za-z0-9_-]`; `Bearer ` followed by 8 or more non-whitespace characters; the value of an `api_key=`, `key=` or `token=` query or form parameter; or a run of 32 or more characters from `[A-Za-z0-9_-]`.
- **LLM_Unavailable_Error**: The error the LLM_Client raises when a completion cannot be obtained from the provider.
- **Structured_Output_Caller**: The LLM_Provider_Layer component that requests a JSON object, validates it against a target Pydantic model and the Citation_Validator, and sends Repair_Requests.
- **Repair_Request**: A follow-up LLM_Call that returns the previous response and its validation errors to the LLM and asks for a corrected JSON object.
- **StructuredOutputError**: The error the Structured_Output_Caller raises when no valid object is obtained after the allowed Repair_Requests.
- **Tool_Adapter**: The LLM_Provider_Layer component that converts MCP tool definitions into the LiteLLM (OpenAI-compatible) tools format and filters them to the Allowed_Tool_Set.
- **Allowed_Tool_Set**: The MCP tools the LLM may call: `get_factory_context`, `get_eol_summary`, `get_product_traces`, `get_equipment_events`, `get_process_changes` and `get_reference_sample_checks`.
- **Industrial_MCP_Server**: The MCP server of the industrial-mcp-server spec, one stdio process per Dataset.
- **MCP_Client_Manager**: The investigation-api component that holds one MCP stdio session per Dataset and records every MCP call with its case_id.
- **MCP_Call_ID**: The call_id carried by every Industrial_MCP_Server response.
- **Dataset**: A generated simulator dataset, as defined in the virtual-factory-simulator spec.
- **Dataset_ID**: The opaque identifier of a Dataset (`ds-00`, `ds-01`, `ds-02` or `ds-03`).
- **Factory_DB**: The SQLite file of a Dataset containing observable system data, as defined in the virtual-factory-simulator spec.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ`, as defined in the virtual-factory-simulator spec.
- **Scenario_Registry**: The simulator component that lists Datasets with user-facing labels and descriptions.
- **Scenario_Key**: The simulator identifier of a scenario (`baseline`, `a`, `b` or `c`).
- **World_State**: The hidden physical truth of a Dataset, as defined in the virtual-factory-simulator spec.
- **Ground_Truth**: The answer key of a Dataset, as defined in the virtual-factory-simulator spec.
- **EOL_Tester**: One of the end-of-line test equipment units, EOL-A or EOL-B.
- **FAIL_Rate**: For a given set of first (non-retest) historical EOL tests, the number of tests with result FAIL divided by the total number of tests in the set.
- **Reference_Sample_Check**: A measurement of a known reference sample on an EOL_Tester, where deviation equals measured minus nominal.
- **Conclusion_Category**: The shared enum with values TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **Support_Level**: The shared ordered enum with values LOW < MEDIUM < HIGH.
- **Analytics_Module**: The package `backend/analytics` containing the Anomaly_Detector, the Analyzers and the Timeline_Builder as pure functions.
- **Analytics_Settings**: The pydantic-settings model holding the analytics thresholds and windows listed in Requirement 6.
- **Data_Range**: The interval from the earliest to the latest first historical EOL test ts of a Dataset, as reported by `get_factory_context`, both ends inclusive.
- **Baseline_Window**: The interval from the Data_Range start (inclusive) to the Data_Range start plus ANALYTICS_BASELINE_HOURS (exclusive).
- **Detection_Window**: The interval from the Data_Range end minus ANALYTICS_DETECTION_HOURS (inclusive) to the Data_Range end (inclusive).
- **Anomaly_Threshold**: For one EOL_Tester, ANOMALY_RATE_RATIO multiplied by the larger of its Baseline_Window FAIL_Rate and ANOMALY_RATE_FLOOR.
- **Anomaly_Detector**: The Analytics_Module function `detect_anomaly` that decides, per EOL_Tester, whether the Detection_Window FAIL_Rate is anomalous.
- **Anomaly_Result**: The output of the Anomaly_Detector: a status (ANOMALY, NO_ANOMALY or INSUFFICIENT_DATA), the window bounds, one row per EOL_Tester, the list of flagged EOL_Testers, the anomalies list and the Detected_Anomaly_Window, as defined in Requirement 7.
- **Detected_Anomaly_Window**: The interval {start, end} of the Detection_Window that the Anomaly_Detector used, reported in the Anomaly_Result as `detected_window`; derived from observable data only and distinct from the hidden Anomaly_Window of the Ground_Truth.
- **Analyzer**: One of the deterministic Analytics_Module functions of Requirements 8 to 10 that turn MCP tool outputs into Findings.
- **Finding**: One analyzer result with a stable finding_key, kind, source_system, title and summary template parameters, data, Record_Refs and MCP_Call_IDs, from which exactly one Evidence_Item is created.
- **Absence_Finding**: A Finding stating that an expected kind of record does not exist in a stated interval.
- **Anomaly_Onset**: For one flagged EOL_Tester, the start of the first time bucket at or after the Baseline_Window end in which the tester has at least ANOMALY_ONSET_MIN_TESTS first historical tests and a FAIL_Rate greater than its Anomaly_Threshold.
- **Timeline_Builder**: The Analytics_Module function that merges dated events into an ordered list of Timeline_Entries.
- **Timeline_Entry**: One timeline record with fields ts, source_system (MES, PPM, EOL, ANALYTICS or VERIFICATION), description and evidence_id.
- **Evidence_Registry**: The package `backend/evidence` component that creates, stores (through the Store) and reads Evidence_Items of a Case.
- **Evidence_Item**: An immutable evidence record with fields id, case_id, kind, source_system, title, summary, data, record_refs, mcp_call_ids and created_at.
- **Ref_Rows**: The `ref_rows` member of Evidence_Item data: one entry per Record_Ref of the Evidence_Item with the key fields of the referenced row, as defined in Requirement 12.
- **Evidence_ID**: The identifier of an Evidence_Item, of the form `EV-` followed by a zero-padded sequence number of at least three digits (`EV-001`, `EV-002`, …).
- **Evidence_Kind**: One of `statistic`, `event`, `record`, `verification` or `absence`.
- **Record_Ref**: A string of the form `<table>:<id>` naming one Factory_DB table and the primary-key value of one row in it.
- **Citation**: An occurrence of an Evidence_ID in LLM output, either in a citation list field or in free text.
- **Citation_Validator**: The `backend/evidence` function that checks every Citation in an LLM output against the Evidence_Registry of the Case.
- **Hypothesis**: An LLM-generated candidate explanation with fields hypothesis_id, category, title, statement, supporting_evidence, contradicting_evidence, missing_evidence, support and recommended_verification_types.
- **Hypothesis_Set**: The validated list of 1 to 5 Hypotheses produced by one hypothesis generation.
- **Hypothesis_Round**: One entry in the hypothesis history of a Case: round number, Hypothesis_Set and created_at.
- **Hypothesis_Generator**: The `backend/agent` component that builds the hypothesis prompt, calls the Structured_Output_Caller, assigns hypothesis_ids and applies the Support_Guardrail.
- **Evidence_Support**: The enum HIGH, MEDIUM, LOW, INSUFFICIENT describing how strongly the cited evidence supports a Hypothesis, labelled "evidence support" and never expressed as a probability.
- **Support_Guardrail**: The `backend/agent` function that enforces the Evidence_Support rules of Requirement 15 on a Hypothesis_Set.
- **Context_Builder**: The `backend/agent` component that assembles the LLM context of a Case from structured summaries.
- **Evidence_Payload_Cap**: The maximum number of characters of evidence content in one LLM_Call, set by EVIDENCE_PAYLOAD_CAP_CHARS (default 24,000).
- **Investigation_Graph**: The LangGraph StateGraph of a Case; this spec defines its first segment.
- **Graph_State**: The typed state of the Investigation_Graph.
- **Case**: One investigation of one Dataset, identified by case_id and owned by the investigation-api spec.
- **Case_Status**: The status of a Case, one of CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM and FAILED, defined by the Case_Status model of the verification-loop spec; this spec sets RUNNING, FAILED_LLM and FAILED through that model.
- **Active_Case_Status**: The Case_Status values CREATED, RUNNING, AWAITING_APPROVAL and CONCLUDING, which block a new Case and a Dataset reset; FAILED_LLM is not an Active_Case_Status.
- **Evidence_Collector**: The `collect_evidence` node, consisting of the Baseline_Collection_Set and the Tool_Loop.
- **Baseline_Collection_Set**: The fixed, deterministic list of MCP calls the Evidence_Collector makes for every Case with status ANOMALY.
- **Failed_SN_Sample**: The deterministic list of up to 20 failed SNs, defined in Requirement 18, for which the Evidence_Collector requests product traces.
- **Tool_Loop**: The LLM tool-calling loop inside the Evidence_Collector.
- **Case_Budget**: The per-Case limits CASE_MAX_MCP_CALLS (default 20) and CASE_MAX_LLM_CALLS (default 40), shared with the verification-loop spec.
- **Checkpointer**: The langgraph-checkpoint-sqlite AsyncSqliteSaver that persists Graph_State after every node, with thread_id equal to case_id.
- **Case_Event_Catalog**: The canonical list of case event types and their minimal payloads, owned by the investigation-api spec; every case event is persisted with a per-Case seq and streamed over SSE.
- **Progress_Event**: A persisted, sequenced case event of a Case whose type and minimal payload are defined by the Case_Event_Catalog, and that the investigation-api spec streams over SSE.
- **Audit_Event**: An audit-trail-only record about a tool control or analysis decision: `tool_call_rejected`, `tool_missing` or `analysis_skipped`. Each Audit_Event is emitted as a Case_Event_Catalog event of type `audit` with payload `{name, actor, details}`, where `name` is that value, `actor` is `system` and `details` is a JSON object describing the decision.
- **Case_Audit**: The per-Case audit trail in the Store: the LLM_Call_Records, plus the Audit_Events, which are persisted as `audit` events in the case event log.
- **Store**: The persistence layer of the investigation-api spec (`app.db`).
- **Verification_Loop**: The nodes of the verification-loop spec that follow this graph segment.

## Requirements

### Requirement 1: LLM Provider Configuration

**User Story:** As an operator, I want to choose the LLM provider and model through environment variables only, so that I can switch providers without code changes.

#### Acceptance Criteria

1. THE LLM_Settings SHALL load the following environment variables with these defaults: LLM_MODEL (default `deepseek/deepseek-flash`), LLM_PROVIDER (default unset), LLM_API_KEY (default unset), LLM_BASE_URL (default unset), LLM_THINKING (default false), LLM_TIMEOUT_S (default 60) and LLM_MAX_RETRIES (default 2).
2. WHEN LLM_MODEL contains no `/` and LLM_PROVIDER is set, THE LLM_Client SHALL use `<LLM_PROVIDER>/<LLM_MODEL>` as the Effective_Model.
3. WHEN LLM_MODEL contains a `/`, or LLM_PROVIDER is unset, THE LLM_Client SHALL use LLM_MODEL unchanged as the Effective_Model.
4. THE LLM_Client SHALL send every completion through LiteLLM with the Effective_Model, with LLM_API_KEY as the API key when it is set, with LLM_BASE_URL as the API base URL when it is set, and with LLM_TIMEOUT_S as the request timeout in seconds.
5. WHILE LLM_THINKING is false, THE LLM_Client SHALL add to every completion request the thinking-disable option that the Thinking_Option_Table lists for the Provider_Prefix of the Effective_Model, and SHALL add no thinking option when the Provider_Prefix is absent from the Thinking_Option_Table.
6. WHILE LLM_THINKING is true, THE LLM_Client SHALL add no thinking-disable option to any completion request.
7. THE LLM_Provider_Layer SHALL contain no provider-specific code path other than the Thinking_Option_Table and the No_Key_Provider_Set, so that switching among OpenAI, Gemini, Qwen/DashScope, OpenRouter, Ollama and DeepSeek requires changes to environment variables only.
8. IF LLM_TIMEOUT_S is not a positive number, LLM_MAX_RETRIES is not an integer from 0 to 10 inclusive, or LLM_THINKING is not a boolean value, THEN THE LLM_Settings SHALL fail to load with a validation error that names the invalid variable.
9. THE LLM_Client SHALL be the only module of the backend that imports `litellm`, enforced by an import-linter contract.

### Requirement 2: LLM Health Check and Secret Protection

**User Story:** As an operator, I want a real health check of the configured LLM and a guarantee that the API key never leaks, so that investigations start only when the model works and credentials stay private.

#### Acceptance Criteria

1. WHEN the LLM_Health_Check refresh operation is invoked and the LLM_Settings are complete, THE LLM_Health_Check SHALL send one real completion with a fixed prompt and a maximum of 8 output tokens to the Effective_Model, and SHALL set the Health_Result status to OK when a completion response is received.
2. IF LLM_MODEL is empty, or LLM_API_KEY is unset or empty while the Provider_Prefix is not in the No_Key_Provider_Set, THEN THE LLM_Health_Check SHALL set the Health_Result status to MISCONFIGURED with a reason that names the missing variable, without sending any network request.
3. IF the provider rejects the credentials or reports that the model does not exist, THEN THE LLM_Health_Check SHALL set the Health_Result status to MISCONFIGURED with a sanitized reason.
4. IF the health completion times out, the connection fails, or the provider returns any other error after LLM_MAX_RETRIES transport retries, THEN THE LLM_Health_Check SHALL set the Health_Result status to UNAVAILABLE with a sanitized reason.
5. THE LLM_Health_Check SHALL cache the latest Health_Result with its checked_at UTC_Timestamp, and SHALL return the cached Health_Result from its read operation without sending any network request.
6. WHILE no refresh has completed since process start, THE LLM_Health_Check SHALL return a cached Health_Result with status UNAVAILABLE and reason "not yet checked".
7. WHEN the refresh operation is invoked while another refresh is in progress, THE LLM_Health_Check SHALL wait for the in-progress health completion and return its Health_Result instead of sending a second health completion.
8. THE LLM_Health_Check SHALL NOT count health completions toward any Case_Budget and SHALL NOT record them in any Case_Audit.
9. THE LLM_Settings SHALL hold LLM_API_KEY as a secret value whose string representation and repr do not contain the key.
10. THE LLM_Provider_Layer SHALL NOT include the LLM_API_KEY value in any log record, Health_Result, exception message, LLM_Call_Record, Progress_Event or Audit_Event, and SHALL pass every provider error message through the Redactor before it stores, logs or raises it.
11. FOR ALL text values s, THE Redactor SHALL return a text that contains neither the configured LLM_API_KEY value nor any Key_Like_String, in which each removed occurrence is replaced by `[REDACTED]`, and for which applying the Redactor a second time returns an identical text.

### Requirement 3: LLM Call Execution and Accounting

**User Story:** As an auditor, I want every LLM call recorded with its cost and timing and never replaced by substitute text, so that I can trace what the model actually produced.

#### Acceptance Criteria

1. THE LLM_Client SHALL require a case_id and a purpose for every LLM_Call. The purposes of this spec are `tool_loop`, `hypotheses` and `repair`; the Verification_Loop may add further purposes.
2. IF a completion request fails with a timeout, a connection error, HTTP status 429 or an HTTP status from 500 to 599, THEN THE LLM_Client SHALL retry the same request up to LLM_MAX_RETRIES times with a delay of 1 second multiplied by 2 to the power of (retry number minus 1) before each retry.
3. IF a completion request fails with any HTTP status from 400 to 499 other than 429, THEN THE LLM_Client SHALL NOT retry the request.
4. IF a completion cannot be obtained after the allowed transport retries, THEN THE LLM_Client SHALL raise an LLM_Unavailable_Error with a sanitized reason, SHALL return no completion text, and SHALL set the cached Health_Result to UNAVAILABLE with that reason and the current checked_at.
5. THE LLM_Client SHALL count each LLM_Call, including all its transport retries, as exactly one LLM call toward the CASE_MAX_LLM_CALLS Case_Budget.
6. WHEN an LLM_Call finishes, successfully or not, THE LLM_Client SHALL write an LLM_Call_Record to the Case_Audit through the Store with: case_id, a per-Case call sequence number, purpose, Effective_Model, prompt tokens, completion tokens and total tokens (null when the provider does not report them), latency in milliseconds, transport attempt count, outcome (`ok` or the error class name) and started_at.
7. THE LLM_Client SHALL store the prompt text and the response text of each LLM_Call_Record truncated to LLM_AUDIT_TEXT_MAX_CHARS characters each (default 20,000), together with the original length and a flag stating whether truncation occurred, after applying the Redactor.
8. THE LLM_Provider_Layer SHALL contain no code path that returns completion text, tool calls or structured objects not received from the provider, and SHALL provide no fallback, demo or rule-based mode.

### Requirement 4: Structured Output

**User Story:** As an agent developer, I want LLM outputs validated against typed schemas with bounded repair, so that downstream code only receives well-formed objects.

#### Acceptance Criteria

1. WHEN the Structured_Output_Caller is invoked with a target Pydantic model, messages, a case_id and a purpose, THE Structured_Output_Caller SHALL send a completion with `response_format={"type":"json_object"}` and a system message that contains the JSON Schema of the target model serialized with sorted keys.
2. THE Investigation_Engine SHALL define every Pydantic model used as a Structured_Output_Caller target with extra fields forbidden.
3. WHEN the response text parses as one JSON object, validates against the target model and passes the Citation_Validator, THE Structured_Output_Caller SHALL return the validated model instance.
4. IF the response text is not one JSON object, fails validation against the target model, or contains a Citation that the Citation_Validator rejects, THEN THE Structured_Output_Caller SHALL send a Repair_Request containing the previous response text and up to 20 errors, each with the field path and a sanitized message, and the list of rejected Evidence_IDs if any.
5. THE Structured_Output_Caller SHALL send at most 2 Repair_Requests per invocation, so that one invocation causes at most 3 LLM_Calls, and SHALL record each LLM_Call_Record with its attempt number (0 for the first request, 1 and 2 for repairs).
6. IF the response of the last allowed attempt is not one JSON object or fails validation against the target model, THEN THE Structured_Output_Caller SHALL raise a StructuredOutputError containing the attempt count and the sanitized validation errors of the last attempt, and SHALL return no partial object.
7. IF the response of the last allowed attempt validates against the target model but still contains rejected Citations, THEN THE Structured_Output_Caller SHALL apply the citation drop rule of Requirement 13 instead of raising a StructuredOutputError.
8. IF sending a further attempt would exceed the CASE_MAX_LLM_CALLS Case_Budget, THEN THE Structured_Output_Caller SHALL send no request and SHALL raise a budget-exhausted error.

### Requirement 5: Tool Exposure to the LLM

**User Story:** As a system designer, I want the LLM to see only read-only investigation tools in the standard tools format, so that it cannot run verifications or bypass evidence summaries.

#### Acceptance Criteria

1. THE Tool_Adapter SHALL convert each MCP tool definition in the Allowed_Tool_Set, as listed by the MCP_Client_Manager, into an entry `{"type": "function", "function": {"name": <MCP tool name>, "description": <MCP tool description>, "parameters": <MCP input schema>}}`.
2. FOR ALL MCP tool lists, THE Tool_Adapter SHALL return a tools list whose names are a subset of the Allowed_Tool_Set, and that never contains `run_simulated_verification`, `get_source_records` or any other tool outside the Allowed_Tool_Set.
3. THE Tool_Adapter SHALL remove the `include_measurements` property from the `properties` and `required` members of the `get_equipment_events` parameters schema.
4. WHEN the Investigation_Engine executes an LLM-requested `get_equipment_events` call, THE Investigation_Engine SHALL set `include_measurements` to false, replacing any value supplied by the LLM.
5. IF the LLM requests a tool outside the Allowed_Tool_Set, THEN THE Investigation_Engine SHALL NOT execute it, SHALL return to the LLM a tool message with error code TOOL_NOT_ALLOWED, and SHALL record an Audit_Event `tool_call_rejected` with the requested tool name.
6. IF the arguments of an LLM-requested tool call are not a JSON object, THEN THE Investigation_Engine SHALL NOT execute the call and SHALL return to the LLM a tool message with error code INVALID_ARGUMENT.
7. IF the Industrial_MCP_Server returns a structured error for an LLM-requested call, THEN THE Investigation_Engine SHALL return to the LLM a tool message containing the error code and the sanitized error message.
8. IF a tool of the Allowed_Tool_Set is missing from the MCP tool list, THEN THE Tool_Adapter SHALL omit it from the tools list and the Investigation_Engine SHALL record an Audit_Event `tool_missing` with the tool name.

### Requirement 6: Analytics Function Contract

**User Story:** As a quality engineer, I want every statistic computed by deterministic, reproducible code, so that the numbers in an investigation can be checked and repeated.

#### Acceptance Criteria

1. THE Analytics_Module SHALL implement the Anomaly_Detector, every Analyzer and the Timeline_Builder as pure functions whose only inputs are parsed MCP tool outputs, their MCP_Call_IDs and the Analytics_Settings, with no file, network, database, clock or random-number access and no LLM_Call.
2. THE Analytics_Module SHALL import none of `backend.llm`, `backend.agent`, `backend.mcp_client`, `backend.store`, `litellm` and `langgraph`, enforced by an import-linter contract.
3. THE Analytics_Settings SHALL load with these defaults: ANALYTICS_BASELINE_HOURS 2, ANALYTICS_DETECTION_HOURS 3, ANALYTICS_ALPHA 0.01, ANOMALY_RATE_RATIO 2.0, ANOMALY_RATE_FLOOR 0.005, TIMELINE_BUCKET_MINUTES 30, ANOMALY_ONSET_MIN_TESTS 10 and ANALYTICS_MIN_SAMPLE 5.
4. THE Analytics_Module SHALL round output values with round-half-even as follows: rates and shares as fractions to 4 decimal places; p-values, test statistics, slopes, intercepts, odds ratios, means and medians to 4 significant digits; counts as integers.
5. THE Analytics_Module SHALL make every threshold decision (flagged, significant) on unrounded values, and SHALL output both the rounded values and the decision flags.
6. IF a value is undefined or infinite (for example an odds ratio with a zero cell), THEN THE Analytics_Module SHALL output null for that value together with a reason text, and SHALL output no NaN or infinity value.
7. FOR ALL valid inputs, THE Analytics_Module SHALL return outputs whose JSON serialization with sorted keys is byte-identical across repeated calls with the same inputs.
8. THE Analytics_Module SHALL return each Analyzer result as a list of Findings, each with a finding_key that is stable for the same inputs and unique within the Case.

### Requirement 7: Anomaly Detection

**User Story:** As a quality engineer, I want the engine to decide with a stated statistical rule whether an EOL_Tester shows an abnormal FAIL_Rate, so that investigations start only on real signals.

#### Acceptance Criteria

1. THE Anomaly_Detector SHALL compute, for each EOL_Tester listed by `get_factory_context`, the number of first historical tests, the number of FAIL results and the FAIL_Rate in the Baseline_Window and in the Detection_Window, from the `get_eol_summary` outputs for those two windows.
2. THE Anomaly_Detector SHALL compute, for each EOL_Tester, the two-sided Fisher exact test p-value on the 2×2 table of FAIL and PASS counts in the Baseline_Window versus the Detection_Window.
3. THE Anomaly_Detector SHALL flag an EOL_Tester if and only if its p-value is less than ANALYTICS_ALPHA and its Detection_Window FAIL_Rate is greater than or equal to its Anomaly_Threshold.
4. THE Anomaly_Detector SHALL return an Anomaly_Result with status ANOMALY when at least one EOL_Tester is flagged, and with status NO_ANOMALY otherwise, except as stated in criterion 6.
5. THE Anomaly_Result SHALL contain, for each EOL_Tester, the tester_id, the test and FAIL counts and FAIL_Rate of both windows, the p-value, the Anomaly_Threshold and the flagged decision, plus the bounds of both windows as UTC_Timestamps.
6. IF the Data_Range is shorter than ANALYTICS_BASELINE_HOURS plus ANALYTICS_DETECTION_HOURS, THEN THE Anomaly_Detector SHALL return status INSUFFICIENT_DATA and flag no EOL_Tester.
7. IF an EOL_Tester has zero first historical tests in the Baseline_Window or in the Detection_Window, THEN THE Anomaly_Detector SHALL NOT flag that EOL_Tester and SHALL state "no tests in window" as the reason in its row.
8. THE Anomaly_Detector SHALL produce one Finding of kind statistic and source_system ANALYTICS per EOL_Tester row, whose Record_Refs are taken from the failed SN sample of that tester in the Detection_Window output.
9. THE Anomaly_Result SHALL contain an `anomalies` list with one entry per flagged EOL_Tester, ordered by tester_id, each with equipment_id (the tester_id), baseline_rate (the Baseline_Window FAIL_Rate), window_rate (the Detection_Window FAIL_Rate), counts (the test and FAIL counts of both windows) and p_value, and a `detected_window` {start, end} equal to the bounds of the Detection_Window used, which is the Detected_Anomaly_Window; the anomalies list SHALL be empty for status NO_ANOMALY or INSUFFICIENT_DATA, and the detected_window SHALL never be taken from the Ground_Truth Anomaly_Window.

### Requirement 8: Tester Comparison and Stratification

**User Story:** As a quality engineer, I want Is/Is-Not comparisons between testers and stratification by product model and material lot, so that a tester is not blamed for a change in product mix.

#### Acceptance Criteria

1. THE Analyzers SHALL compare the EOL_Testers in the Detection_Window by producing, for each pair of EOL_Testers, both test counts, both FAIL counts, both FAIL_Rates, the rate difference and the two-sided Fisher exact test p-value.
2. THE Analyzers SHALL produce, for each product model, an EOL_Tester comparison in the Detection_Window from the tester × model counts, with both FAIL_Rates and the two-sided Fisher exact test p-value.
3. THE Analyzers SHALL produce, for each product model, its share of first historical tests in the Baseline_Window and in the Detection_Window and the two-sided Fisher exact test p-value on the 2×2 table of that model's test count versus all other models' test count in the two windows.
4. THE Analyzers SHALL produce, for each EOL_Tester and each product model, the model's share of that tester's first historical tests in the Baseline_Window and in the Detection_Window and the two-sided Fisher exact test p-value of that change.
5. THE Analyzers SHALL mark each comparison of criteria 1 to 4 as significant if and only if its unrounded p-value is less than ANALYTICS_ALPHA.
6. THE Analyzers SHALL set a flag `mix_explains_tester_difference` to true if and only if the overall Detection_Window tester comparison is significant, no per-model tester comparison is significant, and at least one model-mix change of criterion 3 is significant.
7. THE Analyzers SHALL produce a material lot Finding from the product traces of the Case: per material_lot, the number and share of traced failed SNs, overall and per EOL_Tester, the largest lot share and the number of distinct lots, with `descriptive_only` set to true and no significance test.
8. IF the Case has no product traces, THEN THE Analyzers SHALL produce an Absence_Finding stating that no product traces are available for material lot comparison.

### Requirement 9: Process Change Analysis

**User Story:** As a quality engineer, I want each process change tested against the ST-20 tightening data and the FAIL_Rate, so that an upstream program change can be identified as a cause.

#### Acceptance Criteria

1. THE Analyzers SHALL produce one Finding of kind event and source_system MES for each row returned by `get_process_changes`, with its change_id, equipment_id, ts, change_type, old_value, new_value and changed_by, and the Record_Ref `process_changes:<change_id>`.
2. IF `get_process_changes` returns zero rows for the Data_Range, THEN THE Analyzers SHALL produce an Absence_Finding stating that no process changes exist between the Data_Range start and end.
3. WHEN a process change concerns the ST-20 equipment, THE Analyzers SHALL split the raw ST-20 measurements of each parameter (angle and torque) into a before set (ts from the previous ST-20 change or the Data_Range start up to but excluding the change ts) and an after set (ts from the change ts up to but excluding the next ST-20 change, or up to the Data_Range end inclusive).
4. WHEN both sets of a parameter contain at least ANALYTICS_MIN_SAMPLE values, THE Analyzers SHALL report for that parameter the two-sided Mann–Whitney U statistic and p-value, the two-sample Kolmogorov–Smirnov statistic and p-value, the count, mean and median of each set and the difference of means, each with its own significant flag.
5. IF either set of a parameter contains fewer than ANALYTICS_MIN_SAMPLE values, THEN THE Analyzers SHALL run no test for that parameter and SHALL state the counts and the reason "insufficient sample" in the Finding.
6. IF the `get_equipment_events` output states that the measurements were truncated, THEN THE Analyzers SHALL set `measurements_truncated` to true in every Finding that uses those measurements.
7. THE Analyzers SHALL compute the FAIL_Rate by program_version by assigning each full-range time bucket to the program_version active at the bucket start, excluding every bucket that contains a change ts strictly inside it, and SHALL report per program_version the test count, FAIL count, FAIL_Rate, the Fisher exact test p-value between consecutive versions and `attribution` set to `eol_test_time`.
8. THE Analyzers SHALL place in process change Findings only summary statistics and at most 50 Record_Refs, consisting of the change's Record_Ref and a deterministic sample of `process_measurements:<meas_id>` references (the first measurements by ts, then meas_id, split equally between the before and after sets).
9. THE Investigation_Engine SHALL NOT place raw measurement values in any Evidence_Item, Progress_Event, Audit_Event or LLM message.

### Requirement 10: Measurement System Analysis – Reference Samples and Retests

**User Story:** As a quality engineer, I want the measurement system checked first through reference samples and retests, so that a tester problem is ruled in or out before product causes are considered.

#### Acceptance Criteria

1. THE Analyzers SHALL fit, for each EOL_Tester with at least 3 Reference_Sample_Checks in the Data_Range, an ordinary least-squares regression of deviation against hours since the Data_Range start, and SHALL report the check count, slope in units per hour, intercept, two-sided slope p-value, r² and a significant flag.
2. IF an EOL_Tester has fewer than 3 Reference_Sample_Checks in the Data_Range, THEN THE Analyzers SHALL report the check count and the reason "insufficient checks" and SHALL fit no regression.
3. THE Analyzers SHALL report, for each EOL_Tester, the count of Reference_Sample_Checks with result FAIL as the out-of-tolerance count, and the ts and result of the latest check.
4. IF an EOL_Tester has zero Reference_Sample_Checks in the Detection_Window, THEN THE Analyzers SHALL produce an Absence_Finding with title "No reference sample checks on <tester_id> in detection window", the window bounds, a count of 0 and the MCP_Call_ID of the `get_reference_sample_checks` response.
5. IF `get_reference_sample_checks` returns an explicit zero-record result for an EOL_Tester over the Data_Range, THEN THE Analyzers SHALL produce an Absence_Finding for the whole Data_Range for that EOL_Tester.
6. THE Analyzers SHALL group the historical retests of the full-range retest summary by original EOL_Tester and retest EOL_Tester, and SHALL report per group the retest count, PASS count, FAIL count and PASS share.
7. IF there are zero historical retests with ts in the Detection_Window, THEN THE Analyzers SHALL produce an Absence_Finding stating that no retests exist in the Detection_Window.
8. THE Analyzers SHALL use `reference_sample_checks:<check_id>` Record_Refs for reference sample Findings and `eol_tests:<test_id>` Record_Refs for retest Findings.

### Requirement 11: Investigation Timeline

**User Story:** As a quality engineer, I want one ordered timeline across MES, PPM, EOL and analytics, so that I can see what changed before the anomaly started.

#### Acceptance Criteria

1. THE Timeline_Builder SHALL create a Timeline_Entry for each process change (source_system MES), each equipment event returned by any `get_equipment_events` call of the Case (source_system PPM), each Reference_Sample_Check (source_system EOL) and the Anomaly_Onset of each flagged EOL_Tester (source_system ANALYTICS).
2. THE Timeline_Builder SHALL set each Timeline_Entry description from a fixed template per entry type filled only with field values of the underlying record or Finding.
3. THE Timeline_Builder SHALL set the evidence_id of each Timeline_Entry to the Evidence_ID of the Evidence_Item created from the Finding or tool output that contains the entry's record.
4. THE Timeline_Builder SHALL order Timeline_Entries by ts ascending, then by source_system in the order MES, PPM, EOL, ANALYTICS, VERIFICATION, then by evidence_id ascending.
5. THE Timeline_Builder SHALL compute the Anomaly_Onset from the time buckets of the full-range `get_eol_summary` output with bucket width TIMELINE_BUCKET_MINUTES.
6. IF a flagged EOL_Tester has no time bucket that meets the Anomaly_Onset definition, THEN THE Timeline_Builder SHALL create no onset entry for it and THE Analyzers SHALL produce a Finding stating "onset not determined" for that EOL_Tester.
7. THE Timeline_Builder SHALL accept additional entries of source_system VERIFICATION from the Verification_Loop and SHALL apply the same ordering to them.

### Requirement 12: Evidence Registry

**User Story:** As an auditor, I want every piece of evidence created by deterministic code with traceable sources, so that every claim in an investigation can be followed back to factory records.

#### Acceptance Criteria

1. THE Evidence_Registry SHALL create exactly one Evidence_Item per Finding, with fields id, case_id, kind (an Evidence_Kind), source_system (MES, PPM, EOL, ANALYTICS or VERIFICATION), title, summary, data, record_refs, mcp_call_ids and created_at (UTC_Timestamp).
2. THE Evidence_Registry SHALL assign Evidence_IDs per Case in creation order starting at `EV-001`, incrementing by 1 without gaps, zero-padded to three digits and extended to more digits after `EV-999`.
3. THE Evidence_Registry SHALL create Evidence_Items only from Findings and from verification results passed by Verification_Loop code, and SHALL provide no operation that creates an Evidence_Item from LLM output; an import-linter contract SHALL forbid `backend.llm` from importing the Evidence_Registry.
4. THE Evidence_Registry SHALL set the title and summary of each Evidence_Item from a fixed template per finding type filled only with Finding values, so that FOR ALL Findings, the same Finding yields the same title and summary.
5. THE Evidence_Registry SHALL set kind absence for every Absence_Finding.
6. THE Evidence_Registry SHALL store at most 50 Record_Refs per Evidence_Item, each naming a table of the Factory_DB schema, and SHALL reject a Finding containing a malformed Record_Ref with an error that names it.
7. THE Evidence_Registry SHALL store at least one MCP_Call_ID per Evidence_Item, each belonging to an MCP call recorded for the same Case.
8. THE Evidence_Registry SHALL store data that is JSON-serializable, contains no NaN or infinity value and, excluding its Ref_Rows member, serializes to at most 4,000 characters.
9. WHEN a Finding with a finding_key that already has an Evidence_Item in the Case is added again, THE Evidence_Registry SHALL return the existing Evidence_Item and SHALL assign no new Evidence_ID.
10. THE Evidence_Registry SHALL persist Evidence_Items through the Store, SHALL return them in Evidence_ID order and SHALL NOT modify an Evidence_Item after creation.
11. THE Evidence_Registry SHALL store in the data of each Evidence_Item a Ref_Rows member with one entry per Record_Ref, in record_refs order, containing the Record_Ref and the key fields of the referenced row that apply to its table: for `eol_tests` sn, tester_id, ts, result and is_retest; for `process_measurements` sn, equipment_id, ts and program_version; for other tables the applicable subset of sn, tester_id or equipment_id, ts and result.
12. THE Evidence_Registry SHALL take the Ref_Rows field values from the MCP tool output that produced the Finding (for a `get_eol_summary` failed SN sample entry, result FAIL and is_retest false follow from the tool contract), SHALL set a field to null when that output neither reports nor implies it, and SHALL make no additional MCP call to fill Ref_Rows, so that the Verification_Loop can build its candidate SN list from the Evidence_Registry alone.

### Requirement 13: Citation Validation

**User Story:** As an auditor, I want every Evidence_ID the LLM cites to be checked against the Case registry, so that no hypothesis rests on invented evidence.

#### Acceptance Criteria

1. THE Citation_Validator SHALL extract every Citation from an LLM output: every substring matching `EV-[0-9]+` in any string value at any depth, and every entry of a citation list field (`supporting_evidence`, `contradicting_evidence` and any citation list defined by the Verification_Loop).
2. THE Citation_Validator SHALL accept a Citation if and only if an Evidence_Item with that exact Evidence_ID exists in the Evidence_Registry of the same Case.
3. IF a citation list entry does not exactly match the Evidence_ID form, THEN THE Citation_Validator SHALL reject that entry as an invalid Citation.
4. WHEN the Citation_Validator rejects at least one Citation, THE Structured_Output_Caller SHALL send a Repair_Request that lists the rejected Citations and the Evidence_IDs of the Case, and this Repair_Request SHALL count toward the maximum of 2 Repair_Requests.
5. IF Citations are still rejected after the last allowed attempt, THEN THE Citation_Validator SHALL drop every top-level item (for example one Hypothesis) that still contains a rejected Citation, and THE Investigation_Engine SHALL emit one `citation_dropped` Progress_Event per dropped item with payload {item (the item's position and category if any), invalid_ids (the rejected Citations)}.
6. IF dropping items leaves zero items in an output that requires at least one, THEN THE Structured_Output_Caller SHALL raise a StructuredOutputError with the reason "no items with valid citations".
7. FOR ALL LLM outputs and Evidence_Registries, THE Citation_Validator SHALL return an output in which every remaining Citation exists in the Evidence_Registry of the Case.
8. THE Citation_Validator SHALL be a deterministic function of the LLM output and the set of Evidence_IDs of the Case.

### Requirement 14: Hypothesis Model and Generation

**User Story:** As a quality engineer, I want the LLM to propose a small set of distinct, evidence-cited hypotheses in a fixed structure, so that I can compare competing explanations.

#### Acceptance Criteria

1. THE Hypothesis model SHALL define: hypothesis_id (`H-` followed by a positive integer), category (a Conclusion_Category other than INSUFFICIENT_EVIDENCE), title (1 to 120 characters), statement (1 to 1,000 characters), supporting_evidence (list of Evidence_IDs), contradicting_evidence (list of Evidence_IDs), missing_evidence (0 to 5 texts of 1 to 300 characters), support (an Evidence_Support value) and recommended_verification_types (a list without duplicates whose values are `cross_retest`, `reference_sample_check` or `process_config_check`).
2. THE Hypothesis_Set model SHALL contain 1 to 5 Hypotheses with pairwise different categories.
3. IF a Hypothesis lists the same Evidence_ID in both supporting_evidence and contradicting_evidence, THEN THE Hypothesis model SHALL fail validation.
4. THE Hypothesis model SHALL contain no field for a probability, confidence or likelihood value and SHALL reject extra fields.
5. THE Hypothesis_Generator SHALL use as the Structured_Output_Caller target a schema without hypothesis_id, and SHALL assign each hypothesis_id in code: the hypothesis_id already used for the same category in the hypothesis history of the Case, or else the next unused `H-<n>` number.
6. WHEN the `generate_hypotheses` node runs, THE Hypothesis_Generator SHALL build the context with the Context_Builder, call the Structured_Output_Caller with purpose `hypotheses`, apply the Support_Guardrail, append a Hypothesis_Round to the hypothesis history of the Graph_State, persist it through the Store and emit a `hypotheses_updated` Progress_Event.
7. IF the Structured_Output_Caller raises a StructuredOutputError or an LLM_Unavailable_Error, THEN THE Hypothesis_Generator SHALL append no Hypothesis_Round and SHALL create no Hypothesis.

### Requirement 15: Evidence Support Guardrails

**User Story:** As a quality engineer, I want code to cap how strong a hypothesis may claim to be, so that no hypothesis reaches HIGH support without a verification result.

#### Acceptance Criteria

1. THE Support_Guardrail SHALL run on every Hypothesis_Set after the Citation_Validator and before the Hypothesis_Set is stored, including Hypothesis_Sets produced by the Verification_Loop.
2. IF a Hypothesis has support HIGH and none of its supporting_evidence refers to an Evidence_Item of kind verification, THEN THE Support_Guardrail SHALL set its support to MEDIUM and emit a `support_downgraded` Progress_Event with payload {hypothesis_id, from (the original support), to (the new support), reason "no verification evidence"}.
3. IF a Hypothesis has an empty supporting_evidence list, THEN THE Support_Guardrail SHALL set its support to INSUFFICIENT and emit a `support_downgraded` Progress_Event with payload {hypothesis_id, from, to, reason "no supporting evidence"}.
4. FOR ALL Hypothesis_Sets and Evidence_Registries, THE Support_Guardrail SHALL return a Hypothesis_Set in which no Hypothesis has support HIGH without a supporting Evidence_Item of kind verification and no Hypothesis with empty supporting_evidence has support other than INSUFFICIENT.
5. FOR ALL Hypothesis_Sets, applying the Support_Guardrail twice SHALL yield the same Hypothesis_Set as applying it once, and SHALL never raise a support value.
6. THE Investigation_Engine SHALL map Evidence_Support to Support_Level for evaluation as HIGH → HIGH, MEDIUM → MEDIUM, LOW → LOW and INSUFFICIENT → LOW.
7. THE Investigation_Engine SHALL describe the support field as "evidence support" in the Hypothesis JSON Schema and in every serialized Hypothesis, and SHALL never convert Evidence_Support to a percentage or probability.

### Requirement 16: LLM Context Construction and Information Isolation

**User Story:** As a system designer, I want the LLM to see only structured evidence summaries and never hidden data, so that the investigation cannot be solved by reading the answer key.

#### Acceptance Criteria

1. THE Context_Builder SHALL build the LLM context only from: the factory context summary from `get_factory_context`, the Anomaly_Result summary, Evidence_Item renderings (Evidence_ID, kind, source_system, title, summary and the scalar values of data), tool result summaries of the Tool_Loop and the previous Hypothesis_Rounds of the Case.
2. THE Context_Builder SHALL NOT include in any LLM message raw measurement arrays, Record_Ref lists, the Dataset_ID, any Scenario_Registry label or description, any Scenario_Key, any file path under `data/`, World_State content, Ground_Truth content or the LLM_API_KEY.
3. THE Context_Builder SHALL limit the evidence content of each LLM_Call to the Evidence_Payload_Cap by ordering Evidence_Items as (a) Evidence_Items from the Anomaly_Detector, (b) Evidence_Items of kind verification, (c) all others, each group by Evidence_ID ascending, and including whole Evidence_Items in that order until the next one would exceed the cap.
4. WHEN the Context_Builder omits Evidence_Items, THE Context_Builder SHALL append a note that states the number of omitted Evidence_Items and lists their Evidence_IDs.
5. FOR ALL Evidence_Registries, THE Context_Builder SHALL produce evidence content of at most EVIDENCE_PAYLOAD_CAP_CHARS characters (excluding the omission note), whose included Evidence_Items are a prefix of the ordering of criterion 3, and identical output for identical inputs.
6. THE packages `backend.llm`, `backend.agent`, `backend.analytics` and `backend.evidence` SHALL import neither the `simulator` package nor the world-state module of the Factory_Data_Package, enforced by import-linter contracts, and SHALL contain no string literal `world_state.json` or `ground_truth.json`.
7. THE Investigation_Engine SHALL access Dataset content only through the MCP_Client_Manager using the Dataset_ID and SHALL read no file under `data/<dataset_id>/`.

### Requirement 17: Investigation Graph Structure and Start Precondition

**User Story:** As an agent developer, I want an explicit graph with typed state and named hand-off edges, so that the verification loop can attach to it and every path is predictable.

#### Acceptance Criteria

1. THE Investigation_Graph SHALL be a LangGraph StateGraph whose Graph_State is a typed, JSON-serializable structure with at least: case_id, dataset_id, status, anomaly_result, evidence_ids, hypothesis_history, mcp_call_count, llm_call_count, tool_loop_call_count, round, budget_exhausted and errors.
2. THE Investigation_Graph SHALL contain the nodes `load_case`, `detect_anomaly`, `collect_evidence`, `analyze_evidence` and `generate_hypotheses` with the edges START → `load_case` → `detect_anomaly`, `collect_evidence` → `analyze_evidence` → `generate_hypotheses` → `propose_verification`.
3. WHEN `detect_anomaly` returns status ANOMALY, THE Investigation_Graph SHALL route to `collect_evidence`; WHEN it returns NO_ANOMALY or INSUFFICIENT_DATA, THE Investigation_Graph SHALL route to `generate_report` and make no LLM_Call in this segment.
4. THE Investigation_Graph builder SHALL accept the `propose_verification` and `generate_report` nodes from the Verification_Loop as registered nodes with those exact names.
5. WHEN `load_case` runs for a new Case, THE Investigation_Graph SHALL read case_id and dataset_id from the Store, set the Case_Status to RUNNING, emit a `status_changed` Progress_Event and initialize every counter to 0.
6. WHEN `detect_anomaly` runs, THE Investigation_Graph SHALL call `get_factory_context` and `get_eol_summary` for the Baseline_Window and for the Detection_Window, run the Anomaly_Detector and register its Findings as Evidence_Items.
7. WHEN `analyze_evidence` runs, THE Investigation_Graph SHALL run the Analyzers in the fixed order reference samples, retests, tester comparison, model stratification, material lot, process changes, timeline, and register their Findings in that order, so that identical MCP outputs yield identical Evidence_IDs.
8. IF the cached Health_Result status is not OK when a Case start or resume is requested, THEN THE Investigation_Engine SHALL refuse with error code LLM_UNAVAILABLE and the sanitized health reason, SHALL make no MCP call, SHALL write no checkpoint and SHALL leave the Case_Status unchanged.
9. WHEN `detect_anomaly` completes, THE Investigation_Graph SHALL store the Anomaly_Result, including its anomalies list and Detected_Anomaly_Window, in the Graph_State and in the Case record through the Store, so that the case detail exposes it, and, if the status is ANOMALY, SHALL emit an `anomaly_detected` Progress_Event with payload {anomalies, detected_window}.

### Requirement 18: Evidence Collection

**User Story:** As a quality engineer, I want a fixed baseline of evidence collected for every anomaly plus a bounded set of LLM-chosen queries, so that every investigation covers the essentials and the agent can still explore.

#### Acceptance Criteria

1. WHEN `collect_evidence` runs, THE Evidence_Collector SHALL make the Baseline_Collection_Set calls in this order: `get_eol_summary` for the full Data_Range with bucket width TIMELINE_BUCKET_MINUTES; `get_process_changes` for the full Data_Range; `get_reference_sample_checks` for each EOL_Tester in ascending tester_id order; `get_equipment_events` for the ST-20 equipment over the full Data_Range with `include_measurements` true; and `get_product_traces` for the Failed_SN_Sample.
2. THE Evidence_Collector SHALL define the Failed_SN_Sample as the failed SNs of the Detection_Window `get_eol_summary` output on flagged EOL_Testers, taken in round-robin order over flagged EOL_Testers by ascending tester_id and, per tester, by ascending SN, up to 20 SNs.
3. IF the Failed_SN_Sample is empty, THEN THE Evidence_Collector SHALL skip the `get_product_traces` call.
4. THE Evidence_Collector SHALL reuse the outputs of the `detect_anomaly` calls and SHALL NOT repeat them.
5. WHEN the Baseline_Collection_Set is complete, THE Evidence_Collector SHALL run the Tool_Loop, giving the LLM the Context_Builder context and the Tool_Adapter tools list, and SHALL end the Tool_Loop when the LLM response contains no tool call, when TOOL_LOOP_MAX_CALLS (default 6) tool calls have been requested, or when a Case_Budget is reached.
6. THE Evidence_Collector SHALL count every tool call requested by the LLM, including rejected calls, toward TOOL_LOOP_MAX_CALLS, SHALL execute the tool calls of one LLM response in their listed order, and SHALL NOT execute requested tool calls beyond TOOL_LOOP_MAX_CALLS.
7. WHEN an LLM-requested tool call succeeds, THE Evidence_Collector SHALL create an Evidence_Item from the tool output with a deterministic template and SHALL return to the LLM a tool result summary that includes the new Evidence_ID and is truncated to TOOL_RESULT_MAX_CHARS characters (default 4,000).
8. THE Evidence_Collector SHALL store the final free-text LLM message of the Tool_Loop only in the Case_Audit and SHALL NOT turn it into an Evidence_Item or Finding.
9. THE Evidence_Collector SHALL pass the case_id with every MCP call to the MCP_Client_Manager, increment mcp_call_count for every executed call and emit an `mcp_call` Progress_Event for every executed call.
10. IF a Baseline_Collection_Set call returns error UNAVAILABLE, INTERNAL or LIMIT_EXCEEDED, THEN THE Evidence_Collector SHALL emit an `error` Progress_Event, and THE `analyze_evidence` node SHALL skip every Analyzer that needs that output and record an Audit_Event `analysis_skipped` naming the Analyzer and the error code.
11. IF a `detect_anomaly` call fails with any MCP error, THEN THE Investigation_Engine SHALL set the Case_Status to FAILED with the error code as the reason and stop the graph; FAILED is a terminal Case_Status in the verification-loop Case_Status model.

### Requirement 19: Budgets and Termination

**User Story:** As an operator, I want hard limits on tool calls, LLM calls and graph steps, so that no investigation can loop forever or run up unbounded cost.

#### Acceptance Criteria

1. THE Investigation_Engine SHALL enforce per Case at most CASE_MAX_MCP_CALLS (default 20) executed MCP calls and at most CASE_MAX_LLM_CALLS (default 40) LLM_Calls, using counters in the Graph_State that the Verification_Loop shares.
2. THE Investigation_Engine SHALL count Repair_Requests and every Tool_Loop LLM turn as LLM_Calls toward CASE_MAX_LLM_CALLS.
3. IF executing an MCP call or sending an LLM_Call would exceed its Case_Budget, THEN THE Investigation_Engine SHALL NOT execute or send it, SHALL set budget_exhausted in the Graph_State, SHALL emit a `budget_exhausted` Progress_Event with the budget name, its limit and its used count, and SHALL route the graph to `generate_report`.
4. FOR ALL Case executions, including resumed executions, THE Investigation_Engine SHALL record at most CASE_MAX_MCP_CALLS MCP calls and at most CASE_MAX_LLM_CALLS LLM_Calls for the Case.
5. THE Investigation_Engine SHALL invoke the Investigation_Graph with a recursion_limit equal to GRAPH_RECURSION_LIMIT (default 50).
6. IF the Investigation_Graph reaches its recursion_limit, THEN THE Investigation_Engine SHALL set the Case_Status to FAILED with the reason `recursion_limit_reached`, emit an `error` Progress_Event and run no further node.

### Requirement 20: Checkpointing, Failure Handling and Resume

**User Story:** As an operator, I want investigations to survive crashes and LLM outages without losing work or inventing output, so that a failed case can be resumed where it stopped.

#### Acceptance Criteria

1. THE Investigation_Engine SHALL compile the Investigation_Graph with the Checkpointer writing to CHECKPOINT_DB_PATH and SHALL use the case_id as the thread_id.
2. WHEN a Case is resumed, THE Investigation_Engine SHALL continue from the last checkpoint, SHALL NOT re-execute completed nodes and SHALL NOT repeat their MCP calls or LLM_Calls.
3. WHEN a Case is resumed, THE Investigation_Engine SHALL set mcp_call_count and llm_call_count to the larger of the checkpointed value and the number of MCP calls or LLM_Call_Records recorded for the Case in the Store.
4. WHEN a node that was interrupted before its checkpoint is re-executed, THE Evidence_Registry SHALL return existing Evidence_Items for already-registered finding_keys, so that no Evidence_Item is duplicated.
5. IF an LLM_Unavailable_Error or a StructuredOutputError reaches a node, THEN THE Investigation_Engine SHALL set the Case_Status to FAILED_LLM with a sanitized reason and the failing node name, emit an `error` Progress_Event, stop the graph and substitute no text, Hypothesis or Evidence_Item.
6. WHEN a FAILED_LLM Case whose failed node belongs to this graph segment is retried through the investigation-api spec and the retry function of the verification-loop spec, THE Investigation_Engine SHALL check the start precondition of Requirement 17 criterion 8, set the Case_Status to RUNNING (the FAILED_LLM → RUNNING transition of the verification-loop Case_Status model), emit a `status_changed` Progress_Event and resume from the last checkpoint, re-executing the failed node.
7. WHEN the backend process restarts after a crash, THE Investigation_Engine SHALL be able to resume each RUNNING Case from its last checkpoint by case_id.

### Requirement 21: Progress and Audit Events

**User Story:** As a UI user, I want an ordered stream of what the agent is doing, so that I can follow the investigation as it happens.

#### Acceptance Criteria

1. THE Investigation_Engine SHALL emit, as Progress_Events of the Case_Event_Catalog, the engine-owned event types `status_changed` (for the changes to RUNNING that the Investigation_Engine makes), `node_started`, `node_completed`, `mcp_call`, `llm_call`, `anomaly_detected`, `evidence_added`, `hypotheses_updated`, `support_downgraded`, `citation_dropped`, `budget_exhausted`, `error` and `audit` (for Audit_Events, criterion 7), each with case_id, seq, ts (UTC_Timestamp), type and payload.
2. THE Investigation_Engine SHALL assign seq per Case starting at 1 and incrementing by 1 without gaps or duplicates, continuing from the last persisted seq after a resume.
3. THE Investigation_Engine SHALL persist each Progress_Event through the Store before emitting the next Progress_Event of the same Case.
4. THE Investigation_Engine SHALL emit `node_started` before any other Progress_Event of that node execution and `node_completed` after all other Progress_Events of that node execution.
5. THE Investigation_Engine SHALL include in payloads at least the Case_Event_Catalog fields: for `status_changed`, from, to and reason; for `node_started`, node; for `node_completed`, node and duration_ms; for `mcp_call`, mcp_call_id, tool, arguments_summary (the call arguments as compact JSON truncated to 500 characters), status (`ok` or `error`), error_code (present only when status is `error`) and duration_ms; for `llm_call`, purpose, model (the Effective_Model), tokens_in and tokens_out (null when the provider does not report them), latency_ms and status (`ok` or the error class name); for `anomaly_detected`, anomalies and detected_window as defined in Requirement 7 criterion 9; for `evidence_added`, evidence_id, kind, source_system and title; for `hypotheses_updated`, round and hypotheses (each hypothesis_id, category and support); for `support_downgraded`, hypothesis_id, from, to and reason; for `citation_dropped`, item and invalid_ids; for `budget_exhausted`, budget (the budget name), together with its limit and used count; for `error`, code and message (sanitized, naming the failing node when there is one).
6. THE Investigation_Engine SHALL keep each Progress_Event payload at most 4,000 characters long and free of raw measurement values and of the LLM_API_KEY.
7. THE Investigation_Engine SHALL emit each Audit_Event `tool_call_rejected`, `tool_missing` and `analysis_skipped` as a Case_Event_Catalog event of type `audit`, with case_id, seq, ts and payload `{name, actor, details}`, where `name` is the Audit_Event name, `actor` is `system` and `details` holds the values named in Requirement 5 criteria 5 and 8 and Requirement 18 criterion 10, and SHALL persist it through the Store like every other Progress_Event.
8. THE Investigation_Engine SHALL emit `node_started` and `node_completed` for every node execution of the Investigation_Graph, `mcp_call` for every executed MCP call, `llm_call` for every LLM_Call, and `hypotheses_updated` for every Hypothesis_Round of the Case, including those of Verification_Loop nodes.
9. WHEN the Investigation_Engine sets the Case_Status to FAILED_LLM or FAILED, THE Investigation_Engine SHALL apply the transition through the Case_Status model of the verification-loop spec, which emits the `status_changed` and `completed` events.

### Requirement 22: Test Suite

**User Story:** As a developer, I want deterministic tests on the simulator datasets and opt-in tests against the real LLM, so that statistics are verified exactly and agent behavior is verified by properties.

#### Acceptance Criteria

1. THE test suite SHALL contain deterministic tests, run without the `llm` marker, that obtain MCP outputs from the Industrial_MCP_Server on the simulator Datasets and may read the Ground_Truth and Scenario_Registry.
2. THE deterministic tests SHALL assert that the Anomaly_Detector returns status ANOMALY with EOL-B flagged and EOL-A not flagged for `ds-01`, status ANOMALY with both EOL-A and EOL-B flagged for `ds-02` (the virtual-factory-simulator spec guarantees for each EOL_Tester a final-3-hours FAIL_Rate of at least 2.5 times its first-2-hours FAIL_Rate with a two-sided Fisher exact test p-value below 0.01), status ANOMALY with EOL-B flagged for `ds-03`, and status NO_ANOMALY with no EOL_Tester flagged for `ds-00`.
3. THE deterministic tests SHALL assert for `ds-03` that every per-model EOL_Tester comparison in the Detection_Window (the final 3 hours with the default ANALYTICS_DETECTION_HOURS, for which the virtual-factory-simulator spec guarantees per-model p-values above 0.05) has a p-value greater than 0.05 and that the Model B share change between the Baseline_Window and the Detection_Window has a p-value less than 0.01.
4. THE deterministic tests SHALL assert for `ds-02` that the process change Finding for the ST-20 change from P-2.3 to P-2.4 has an angle Kolmogorov–Smirnov p-value and an angle Mann–Whitney U p-value both less than 0.01.
5. THE deterministic tests SHALL assert for `ds-01` that the EOL-B reference sample regression has a positive slope with a p-value less than 0.01.
6. THE deterministic tests SHALL assert, for every Evidence_Item produced for `ds-00` to `ds-03`, that every Record_Ref resolves through `get_source_records` to an existing record.
7. THE deterministic tests SHALL test the Citation_Validator, the Support_Guardrail, the Context_Builder truncation, the Redactor and the Analytics_Module reproducibility with property-based tests over generated inputs, and SHALL use hand-built LLM-like payloads only as test fixtures, never as product code.
8. THE deterministic tests SHALL assert that, for every Dataset, no LLM message built by the Context_Builder contains a Scenario_Registry label or description, the Dataset_ID or a raw measurement array.
9. THE test suite SHALL mark every test that calls the real LLM with the pytest marker `llm` and SHALL deselect these tests by default.
10. THE `llm` tests SHALL assert against the configured real provider (default DeepSeek) that the Structured_Output_Caller returns a validated object or raises StructuredOutputError after at most 3 LLM_Calls, and that the Tool_Loop executes at most TOOL_LOOP_MAX_CALLS tool calls and no tool outside the Allowed_Tool_Set.
11. THE `llm` tests SHALL run the graph segment for `ds-01`, `ds-02` and `ds-03` and assert that every Citation in every stored Hypothesis exists in the Case Evidence_Registry, that the `ds-01` hypotheses include category TESTER_MEASUREMENT_DRIFT, that the `ds-02` hypotheses include category PROCESS_PARAMETER_DEVIATION, and that no `ds-03` Hypothesis has support HIGH.
12. THE `llm` tests SHALL assert structural properties (categories, support values, Citation validity, counts and limits) and SHALL NOT assert on generated text content.
