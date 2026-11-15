# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent built on LangGraph investigates End-of-Line (EOL) quality anomalies in the fictional Factory Alpha (Line A, stations ST-10, ST-20 and ST-30, EOL_Testers EOL-A and EOL-B, Model A and Model B) through the Industrial_MCP_Server over simulated MES, PPM and EOL data. The key feature is "Next Best Verification": the AI proposes what to verify next, a human approves, a simulated verification runs, and the AI revises its judgment with an audit trail.

This spec covers the second segment of the Investigation_Graph and the backend logic around it: the nodes propose_verification, human_approval, execute_verification, update_hypotheses, finalize_conclusion and generate_report, the loop between them, the Decision contract consumed by the Investigation_API, the Case_Status model, retry after LLM failure, the Report object and its deterministic Markdown rendering, and the automated tests for this segment.

The first segment of the graph (load_case, detect_anomaly, collect_evidence, analyze_evidence, generate_hypotheses), the LLM_Client, the Evidence_Registry, the Citation_Validator, the Hypothesis model and its guardrails, budget accounting, checkpointing and the progress event mechanism are owned by the investigation-engine spec. This spec uses them and adds rules on top of them.

Out of scope: HTTP endpoints and Server-Sent Events (investigation-api spec), the user interface (investigation-workspace-ui spec), PDF generation (the browser prints the rendered report), the implementation of `run_simulated_verification` (industrial-mcp-server spec), and any real equipment, real MES/PLC/SCADA system or real company data.

Assumptions:
- A Proposal_Round is one invocation of propose_verification that ends in an Approval_Payload. A Verification_Round is one invocation of execute_verification after an approve Decision, counted whether the MCP call succeeds or fails. Proposal_IDs use the Proposal_Round number; Approval_IDs use the Verification_Round number. Because at most 2 reject_all Decisions and at most 3 Verification_Rounds are allowed, a case has at most 5 Proposal_Rounds.
- Each invocation of an LLM-backed node in this spec (propose_verification, update_hypotheses, finalize_conclusion and the narrative step of generate_report) makes at most 3 LLM calls: 1 initial call and at most 2 repair calls. Repair calls cover schema, citation, validator and wording failures together, and every call counts against the case LLM budget of 40.
- The Closing_Reserve is 6 LLM calls (3 for finalize_conclusion and 3 for generate_report). One further loop iteration needs 6 LLM calls (3 for propose_verification and 3 for update_hypotheses) and 1 MCP tool call. With the case LLM budget of 40, a new Proposal_Round starts only while at least 12 LLM calls (Closing_Reserve plus 6) remain, that is, while at most 28 LLM calls have been used.
- Evidence_Support values are ordered INSUFFICIENT < LOW < MEDIUM < HIGH. Evidence_Support maps to Support_Level as HIGH → HIGH, MEDIUM → MEDIUM and LOW → LOW. INSUFFICIENT has no Support_Level equivalent.
- A Conclusion with category INSUFFICIENT_EVIDENCE always has support LOW.
- A verification counts as executed only when `run_simulated_verification` returned a result. A verification whose MCP call failed may be proposed again.
- The investigation-engine spec provides, in the data of each Evidence_Item, the key fields of every row named by its record_refs (for `eol_tests`: sn, tester_id, ts, result, is_retest; for `process_measurements`: sn, equipment_id, ts, program_version). The Candidate_SN_List and the Suspected_Scope use only these values and make no additional MCP calls.
- The investigation-engine spec provides the Anomaly_Detection_Result, which its detect_anomaly node stores in the case detail and emits as `anomaly_detected`: the status, the anomalies list (per flagged EOL_Tester: equipment_id, baseline_rate, window_rate, counts and p_value), the Detected_Anomaly_Window {start, end} and the FAIL_Rate metrics. The Detected_Anomaly_Window is derived from observable data and is different from the hidden Anomaly_Window of the Ground_Truth.
- The Case_Event_Catalog of the investigation-api spec defines every case event type and its minimal payload; case events are persisted with a per-case sequence number and streamed over SSE.
- The Banned_Wording_Checker matches phrases case-insensitively on word boundaries after collapsing runs of whitespace to one space, so that "unproven" does not match "proven".
- All wall-clock timestamps in audit events and reports are UTC_Timestamps produced by the shared Time_Util.

Dependencies:
- investigation-engine: LLM_Client (LiteLLM, default model `deepseek/deepseek-flash`, JSON-mode structured output with Pydantic validation, at most 2 repair attempts), Evidence_Registry, Citation_Validator, Hypothesis model and Hypothesis_Guardrails, case budgets (at most 20 MCP tool calls and at most 40 LLM calls per case), AsyncSqliteSaver checkpointing with `thread_id` equal to the case_id, Progress_Events with a per-case sequence number, the Anomaly_Detection_Result with its Detected_Anomaly_Window, and the referenced-row key fields in Evidence_Item data.
- industrial-mcp-server: the tool `run_simulated_verification` with the verification types cross_retest, reference_sample_check and process_config_check, idempotent per approval_id, returning structured errors on failure.
- virtual-factory-simulator: the Datasets `ds-01`, `ds-02` and `ds-03` used by the LLM integration tests, and the shared Conclusion_Category, Support_Level and UTC_Timestamp definitions.
- investigation-api: owns the Case_Event_Catalog, and consumes the Approval_Payload, the decision submission function, the retry function, the Case_Status model and the stored Report. It exposes none of these over HTTP inside this spec.

## Glossary

- **Verification_Loop**: The backend component specified here: the second segment of the Investigation_Graph, the Decision_Validator, the Case_Status model, the Report_Store and the Report_Renderer.
- **Investigation_Engine**: The component specified by the investigation-engine spec that owns the first graph segment, the LLM_Client, the Evidence_Registry, the Citation_Validator, the Hypothesis model, budgets, checkpointing and Progress_Events.
- **Investigation_Graph**: The LangGraph state graph that runs one investigation case, checkpointed with AsyncSqliteSaver under `thread_id` equal to the case_id.
- **Industrial_MCP_Server**: The MCP server specified by the industrial-mcp-server spec that exposes simulated factory data and the tool `run_simulated_verification`.
- **Investigation_API**: The HTTP layer specified by the investigation-api spec.
- **Case**: One investigation of one Dataset, identified by a case_id.
- **Case_State**: The checkpointed graph state of one Case, including hypotheses, Evidence_Items, proposals, Decisions, Judgment_Changes, the Conclusion, counters, budgets and the Audit_Trail.
- **Case_Status**: The status of a Case, one of CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM and FAILED, defined by the Case_Status model of this spec.
- **Active_Case_Status**: The Case_Status values CREATED, RUNNING, AWAITING_APPROVAL and CONCLUDING, which block a new Case and a Dataset reset; FAILED_LLM, COMPLETED and FAILED are not active.
- **Case_Event_Catalog**: The canonical list of case event types and their minimal payloads, owned by the investigation-api spec.
- **LLM_Client**: The Investigation_Engine component that performs structured-output LLM calls with Pydantic validation and repair re-asks.
- **Evidence_Registry**: The Investigation_Engine component that stores Evidence_Items for a Case and assigns Evidence_IDs.
- **Evidence_Item**: One registered piece of evidence with an Evidence_ID, a kind (statistic, event, record, verification or absence), a deterministic template summary and record_refs in the form `table:id`.
- **Evidence_ID**: The identifier of an Evidence_Item in the form `EV-` followed by at least three digits, for example `EV-001`.
- **Citation_Validator**: The Investigation_Engine component that checks Evidence_IDs cited by LLM output. Unknown Evidence_IDs trigger a repair re-ask and, if still present, are dropped with a `citation_dropped` case event.
- **Hypothesis**: A candidate cause with fields hypothesis_id, category (a Conclusion_Category value other than INSUFFICIENT_EVIDENCE), title, statement, supporting Evidence_IDs, contradicting Evidence_IDs, missing_evidence text, support (an Evidence_Support value) and recommended_verification_types.
- **Evidence_Support**: The ordered support value of a Hypothesis: INSUFFICIENT < LOW < MEDIUM < HIGH.
- **Hypothesis_Guardrails**: The Investigation_Engine rules applied to every Hypothesis: support HIGH requires at least one supporting Evidence_Item of kind verification, otherwise support is lowered to MEDIUM; a Hypothesis with zero valid supporting citations gets support INSUFFICIENT.
- **Conclusion_Category**: The shared enum with values TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **Support_Level**: The shared ordered enum with values LOW < MEDIUM < HIGH.
- **Anomaly_Detection_Result**: The Anomaly_Result of the detect_anomaly node, provided by the investigation-engine spec: an anomaly flag (true when its status is ANOMALY), the anomalies list with one entry per anomalous EOL_Tester (equipment_id, baseline_rate, window_rate, counts and p_value), the Detected_Anomaly_Window and the FAIL_Rate metrics.
- **Detected_Anomaly_Window**: The interval {start, end} of the detection window that detect_anomaly used, derived from observable data only and distinct from the hidden Anomaly_Window of the Ground_Truth.
- **FAIL_Rate**: For a set of first (non-retest) EOL tests, the number of tests with result FAIL divided by the number of tests in the set.
- **EOL_Tester**: One of the two end-of-line test equipment units, EOL-A or EOL-B.
- **SN**: The serial number of one product.
- **Verification_Type**: One of cross_retest, reference_sample_check and process_config_check.
- **Candidate_SN_List**: The deterministic list, per EOL_Tester, of SNs whose first EOL test on that EOL_Tester has result FAIL according to the Evidence_Registry.
- **Proposal_Round**: One invocation of propose_verification that ends in an Approval_Payload, numbered from 1 within a Case.
- **Verification_Round**: One invocation of execute_verification after an approve Decision, numbered from 1 within a Case, at most 3 per Case.
- **Verification_Proposal**: A proposed verification with fields proposal_id, rank, verification_type, params, rationale, targets_hypotheses, expected_outcomes and cited_evidence.
- **Proposal_ID**: The identifier of a Verification_Proposal in the form `P-<proposal_round>-<rank>`, for example `P-2-1`.
- **Expected_Outcome**: One entry of a Verification_Proposal's expected_outcomes with fields outcome (text), interpretation (supports, contradicts or neutral) and hypothesis_id.
- **Conclude_Recommendation**: The alternative output of propose_verification that recommends concluding instead of verifying, with a non-empty reason.
- **Proposal_Validator**: The deterministic Verification_Loop function that checks each Verification_Proposal before it is offered to the human.
- **Normalized_Params**: The comparison form of a Verification_Proposal's params: for cross_retest, the sorted list of SNs plus target_tester_id; for reference_sample_check, tester_id; for process_config_check, equipment_id.
- **Approval_Payload**: The JSON object passed to LangGraph `interrupt()` by the human_approval node.
- **Decision**: The human response to an Approval_Payload with fields action (approve, reject_all or conclude), proposal_id (required for approve, forbidden otherwise), note (required with 1 to 500 characters for reject_all; optional with at most 500 characters for approve and conclude) and actor (optional, at most 64 characters, default "engineer").
- **Decision_Validator**: The deterministic Verification_Loop function that checks a Decision before the graph is resumed.
- **Final_Suggestion_Round**: The Proposal_Round that directly follows the second reject_all Decision of a Case.
- **Approval_ID**: The identifier passed to `run_simulated_verification`, in the form `APR-<case_id>-<verification_round>`.
- **Approval_Guard**: The check in execute_verification that refuses to run a verification without a matching approve Decision.
- **Judgment_Change**: The code-computed record of how one Hypothesis changed in one Verification_Round, with fields hypothesis_id, category, before, after, direction (up, down, unchanged, new or removed), because (Evidence_IDs) and rationale (LLM text).
- **Closing_Reserve**: The 6 LLM calls kept available for finalize_conclusion and generate_report.
- **Conclusion**: The final result of a Case with fields category (Conclusion_Category), support (Support_Level), qualifier, statement, cited_evidence, open_questions and conclude_reason.
- **Banned_Phrases**: The phrases "confirmed root cause", "root cause is", "proven", "definitely" and "certainly caused".
- **Banned_Wording_Checker**: The deterministic function that reports every occurrence of a Banned_Phrase in a text.
- **Unavailable_Marker**: The exact text "Narrative unavailable – LLM output failed validation".
- **Report**: The stored, versioned report object of a Case, either full form (10 sections) or short form.
- **Report_Store**: The persistent store of Report versions per Case in the case database.
- **Report_Renderer**: The deterministic function that converts a stored Report into Markdown.
- **Suspected_Scope**: The deterministic list of SNs suspected to be affected, shown in report section 8.
- **Disclaimer**: The fixed text "This report is based on simulated data from a fictional factory. It is decision support only and does not establish a certified root cause. No real equipment was accessed or controlled."
- **Audit_Trail**: The append-only list of audit events in the Case_State, each with an event type, a UTC_Timestamp, an actor and details.
- **Progress_Event**: A case event of the Case_Event_Catalog emitted through the Investigation_Engine progress mechanism, persisted with a per-case sequence number and streamed over SSE by the investigation-api spec.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ` representing an instant in UTC.
- **Ground_Truth**: The hidden answer key of a Dataset, defined by the virtual-factory-simulator spec.
- **Scenario_Registry**: The simulator component that lists Datasets with user-facing labels and descriptions, defined by the virtual-factory-simulator spec.
- **Auto_Approve_Policy**: The test policy that answers every Approval_Payload by approving the rank-1 Verification_Proposal, or by concluding when no Verification_Proposal is offered.

## Requirements

### Requirement 1: Second Graph Segment Topology

**User Story:** As an engine developer, I want a fixed graph topology for the verification loop, so that every case follows the same auditable path from hypotheses to report.

#### Acceptance Criteria

1. THE Verification_Loop SHALL add the nodes propose_verification, human_approval, execute_verification, update_hypotheses, finalize_conclusion and generate_report to the Investigation_Graph, with an edge from generate_hypotheses to propose_verification.
2. THE Investigation_Graph SHALL contain these edges in the second segment and no others: propose_verification → human_approval; propose_verification → finalize_conclusion; human_approval → execute_verification; human_approval → propose_verification; human_approval → finalize_conclusion; execute_verification → update_hypotheses; execute_verification → propose_verification; execute_verification → finalize_conclusion; update_hypotheses → propose_verification; update_hypotheses → finalize_conclusion; finalize_conclusion → generate_report; generate_report → END.
3. THE Investigation_Graph SHALL contain an edge from detect_anomaly to generate_report, taken WHEN the Anomaly_Detection_Result anomaly flag is false.
4. THE Investigation_Graph SHALL contain an edge to generate_report from each first-segment node at which the Investigation_Engine detects budget exhaustion, taken WHEN a budget is exhausted before generate_hypotheses has completed.
5. THE Verification_Loop SHALL implement every routing decision of the second segment as a deterministic function of the Case_State, and SHALL NOT let an LLM output select the next node directly.
6. THE Verification_Loop SHALL use the same Investigation_Graph checkpointer and `thread_id` (the case_id) as the first segment, so that the state after every completed node is checkpointed.

### Requirement 2: Candidate Serial Number List

**User Story:** As an engine developer, I want the LLM to choose retest serial numbers from a code-built list, so that it can never invent serial numbers.

#### Acceptance Criteria

1. WHEN propose_verification starts, THE Verification_Loop SHALL build the Candidate_SN_List from the referenced-row key fields in the Evidence_Item data of the Evidence_Registry, containing for each EOL_Tester the SNs whose first (is_retest false) historical EOL test on that EOL_Tester has result FAIL.
2. THE Verification_Loop SHALL order each EOL_Tester's entries in the Candidate_SN_List by test timestamp descending, then by SN ascending, and SHALL keep at most the first 20 entries per EOL_Tester.
3. WHEN the Case_State is the same, THE Verification_Loop SHALL produce an identical Candidate_SN_List.
4. THE Verification_Loop SHALL pass the Candidate_SN_List to the propose_verification LLM call together with the current Hypotheses, the Evidence_Item summaries and Evidence_IDs, the executed verifications, the rejected Verification_Proposals with their reject notes, the remaining budgets and the Final_Suggestion_Round flag.
5. THE Verification_Loop SHALL include no Ground_Truth content, no Scenario_Registry label or description and no scenario key in any prompt it sends to the LLM_Client.
6. IF the Evidence_Registry contains no first EOL test with result FAIL for an EOL_Tester, THEN THE Verification_Loop SHALL pass an empty list for that EOL_Tester.

### Requirement 3: Verification Proposal Generation

**User Story:** As a quality engineer, I want the AI to propose up to three ranked verifications with expected outcomes, so that I can see what each verification would tell me before I approve it.

#### Acceptance Criteria

1. WHEN propose_verification runs, THE Verification_Loop SHALL request structured output from the LLM_Client that contains either 1 to 3 Verification_Proposal drafts and no Conclude_Recommendation, or zero drafts and one Conclude_Recommendation with a non-empty reason.
2. THE Verification_Loop SHALL require each Verification_Proposal draft to contain a rank, a Verification_Type, params, a non-empty rationale, at least one hypothesis_id in targets_hypotheses, at least one Expected_Outcome, and at least one cited Evidence_ID.
3. THE Verification_Loop SHALL require each Expected_Outcome to contain a non-empty outcome text of at most 200 characters, an interpretation of supports, contradicts or neutral, and a hypothesis_id.
4. WHEN Verification_Proposals pass the Proposal_Validator, THE Verification_Loop SHALL order them by the LLM-given rank, renumber their ranks contiguously from 1, and assign each the Proposal_ID `P-<proposal_round>-<rank>`.
5. IF the LLM output fails schema validation after the LLM_Client repair attempts, or the LLM provider fails, THEN THE Verification_Loop SHALL set the Case_Status to FAILED_LLM and SHALL NOT create any Verification_Proposal or substitute text.
6. THE Verification_Loop SHALL make at most 3 LLM calls per Proposal_Round.
7. WHEN the LLM output is a Conclude_Recommendation, THE Verification_Loop SHALL offer zero Verification_Proposals and SHALL include the Conclude_Recommendation reason in the Approval_Payload.

### Requirement 4: Proposal Validation

**User Story:** As a quality engineer, I want every proposal checked by code before I see it, so that I only approve verifications that are legal and new.

#### Acceptance Criteria

1. THE Proposal_Validator SHALL accept a Verification_Proposal only if its verification_type is cross_retest, reference_sample_check or process_config_check.
2. THE Proposal_Validator SHALL accept a cross_retest Verification_Proposal only if its params contain 1 to 5 distinct SNs, every SN appears in the Candidate_SN_List, and target_tester_id is EOL-A or EOL-B.
3. THE Proposal_Validator SHALL accept a reference_sample_check Verification_Proposal only if its tester_id is EOL-A or EOL-B, and a process_config_check Verification_Proposal only if its equipment_id is ST-10, ST-20 or ST-30.
4. THE Proposal_Validator SHALL reject a Verification_Proposal whose params contain a key not defined for its Verification_Type or lack a required key.
5. THE Proposal_Validator SHALL reject a Verification_Proposal whose Verification_Type and Normalized_Params equal those of an executed verification of the Case or of a Verification_Proposal rejected by a reject_all Decision of the Case.
6. IF two Verification_Proposals of one Proposal_Round have the same Verification_Type and Normalized_Params, THEN THE Proposal_Validator SHALL reject the one with the lower priority (higher LLM-given rank).
7. THE Proposal_Validator SHALL reject a Verification_Proposal whose targets_hypotheses or Expected_Outcome hypothesis_ids reference a hypothesis_id not present in the current Hypotheses, or that has zero valid cited Evidence_IDs after the Citation_Validator has run.
8. WHEN the Proposal_Validator rejects a Verification_Proposal, THE Verification_Loop SHALL drop it, append an audit event `proposal_rejected_by_validator` containing the Proposal_Round, the LLM-given rank, the Verification_Type, the params and the violated rule, and emit a Progress_Event `proposal_rejected_by_validator` with payload {proposal (the Proposal_Round, LLM-given rank, Verification_Type and params), reason (the violated rule)}.
9. IF every Verification_Proposal of an LLM output is rejected by the Proposal_Validator and LLM calls remain within the Proposal_Round limit, THEN THE Verification_Loop SHALL send a repair re-ask to the LLM_Client that lists the violated rules.
10. IF no Verification_Proposal passes the Proposal_Validator after the repair re-asks, THEN THE Verification_Loop SHALL offer zero Verification_Proposals and only the conclude action, with the conclude reason "no valid verification proposal".
11. THE Proposal_Validator SHALL be a pure function of the Verification_Proposal drafts and the Case_State, with no LLM or MCP calls.

### Requirement 5: Human Approval Interrupt

**User Story:** As a quality engineer, I want the investigation to stop and wait for my decision with everything I need on one payload, so that no verification runs without me.

#### Acceptance Criteria

1. WHEN human_approval runs, THE Verification_Loop SHALL call LangGraph `interrupt()` with an Approval_Payload and SHALL set the Case_Status to AWAITING_APPROVAL.
2. THE Approval_Payload SHALL be JSON-serializable and SHALL contain case_id, round (the Proposal_Round), final_round (the Final_Suggestion_Round flag), proposals (the full validated Verification_Proposals), conclude_option, allowed_actions, reject_all_remaining and budgets_remaining.
3. THE Approval_Payload conclude_option SHALL contain available (always true), recommended (true when the LLM returned a Conclude_Recommendation or no Verification_Proposal passed validation) and reason (the Conclude_Recommendation reason, "no valid verification proposal", or null).
4. THE Approval_Payload budgets_remaining SHALL contain the remaining MCP tool calls, the remaining LLM calls and the remaining Verification_Rounds of the Case.
5. THE Approval_Payload allowed_actions SHALL contain approve only if proposals is non-empty, SHALL contain reject_all only if reject_all_remaining is greater than 0 and the conclude reason is not "no valid verification proposal", and SHALL always contain conclude.
6. WHILE the Case_Status is AWAITING_APPROVAL, THE Verification_Loop SHALL make no LLM call and no MCP tool call for the Case.
7. WHILE the Case_Status is AWAITING_APPROVAL, THE Verification_Loop SHALL return the current Approval_Payload of the Case on request.
8. WHEN a Decision passes the Decision_Validator, THE Verification_Loop SHALL resume the Investigation_Graph with `Command(resume=Decision)`.

### Requirement 6: Decision Validation

**User Story:** As an API developer, I want invalid decisions rejected with a clear error before the graph resumes, so that a bad request can never change the case.

#### Acceptance Criteria

1. THE Verification_Loop SHALL provide a decision submission function that takes a case_id and a Decision and runs the Decision_Validator before resuming the Investigation_Graph.
2. IF the Case_Status is not AWAITING_APPROVAL, THEN THE Decision_Validator SHALL reject the Decision with error code `CASE_NOT_AWAITING_APPROVAL`.
3. IF the action is not approve, reject_all or conclude, THEN THE Decision_Validator SHALL reject the Decision with error code `INVALID_ACTION`.
4. IF the action is not in the Approval_Payload allowed_actions and the Decision is not a reject_all covered by criterion 11, THEN THE Decision_Validator SHALL reject the Decision with error code `ACTION_NOT_OFFERED`.
5. IF the action is approve and proposal_id is missing or is not the Proposal_ID of a Verification_Proposal in the current Approval_Payload, THEN THE Decision_Validator SHALL reject the Decision with error code `UNKNOWN_PROPOSAL`.
6. IF the action is reject_all or conclude and a proposal_id is present, THEN THE Decision_Validator SHALL reject the Decision with error code `UNEXPECTED_PROPOSAL_ID`.
7. IF the action is reject_all and the note is missing or contains only whitespace, THEN THE Decision_Validator SHALL reject the Decision with error code `NOTE_REQUIRED`.
8. IF the note is longer than 500 characters, for any action, THEN THE Decision_Validator SHALL reject the Decision with error code `NOTE_TOO_LONG`.
9. WHEN the actor is omitted or null, THE Decision_Validator SHALL set the actor to "engineer".
10. IF the actor is present and is empty, contains only whitespace or is longer than 64 characters, THEN THE Decision_Validator SHALL reject the Decision with error code `INVALID_ACTOR`.
11. IF the action is reject_all and the Case already has 2 reject_all Decisions, THEN THE Decision_Validator SHALL reject the Decision with error code `REJECT_LIMIT_REACHED`.
12. WHEN the Decision_Validator rejects a Decision, THE Verification_Loop SHALL return the error code and a message, SHALL NOT resume the Investigation_Graph, and SHALL leave the Case_State, Case_Status, Audit_Trail and budgets unchanged.
13. THE Decision_Validator SHALL treat approval of any listed Verification_Proposal, including one with rank greater than 1, as a valid approve Decision.
14. WHEN the action is approve or conclude and the note is omitted, THE Decision_Validator SHALL accept the Decision without a note.
15. THE Decision_Validator SHALL use only UPPERCASE_SNAKE_CASE error codes, and the investigation-api spec maps them to HTTP responses as follows: `CASE_NOT_AWAITING_APPROVAL` is returned as HTTP 409 with `error.code` CONFLICT, and every other Decision_Validator error code is a validation error returned as HTTP 400 with the error code in `error.code` of the Error_Body.

### Requirement 7: Decision Handling

**User Story:** As a quality engineer, I want each of my decisions recorded and acted on exactly as given, so that the investigation path reflects my choices.

#### Acceptance Criteria

1. WHEN the Investigation_Graph resumes with a Decision, THE Verification_Loop SHALL append an audit event `decision_recorded` containing the actor, the wall-clock UTC_Timestamp, the action, the Proposal_Round, the proposal_id and a copy of the approved Verification_Proposal (if any), and the note.
2. WHEN the action is approve, THE Verification_Loop SHALL route to execute_verification with the approved Verification_Proposal.
3. WHEN the action is reject_all, THE Verification_Loop SHALL add every Verification_Proposal of the current Approval_Payload to the rejected proposals of the Case, store the note with them, and route to propose_verification.
4. WHEN the action is conclude, THE Verification_Loop SHALL record conclude_reason "human_concluded" and route to finalize_conclusion.
5. WHEN the second reject_all Decision of a Case is recorded, THE Verification_Loop SHALL mark the next Proposal_Round as the Final_Suggestion_Round, set final_round true in its Approval_Payload, and pass the flag to the LLM.
6. WHILE a Case has 2 reject_all Decisions, THE Verification_Loop SHALL set reject_all_remaining to 0 in every subsequent Approval_Payload.
7. THE Verification_Loop SHALL NOT count a reject_all Decision as a Verification_Round.
8. WHEN a Decision is recorded, THE Verification_Loop SHALL emit a Progress_Event `decision_recorded` with payload {action, proposal_id (present only for approve), note (present only when given), actor}.

### Requirement 8: Verification Execution

**User Story:** As a quality engineer, I want the approved verification to run once and its result to become evidence, so that the AI's revised judgment rests on recorded data.

#### Acceptance Criteria

1. THE execute_verification node SHALL be the only code in the Verification_Loop and the Investigation_Engine that calls the MCP tool `run_simulated_verification`.
2. WHEN execute_verification runs after an approve Decision, THE Verification_Loop SHALL increment the Verification_Round counter, generate the Approval_ID `APR-<case_id>-<verification_round>`, and call `run_simulated_verification` with the approved verification_type, params, the Approval_ID and approved_by equal to the Decision actor.
3. THE Verification_Loop SHALL generate an Approval_ID only within execute_verification after an approve Decision has been recorded.
4. WHEN `run_simulated_verification` returns a result, THE Verification_Loop SHALL register exactly one Evidence_Item for it, of kind absence when the reference_sample_check outcome is UNAVAILABLE and of kind verification otherwise.
5. THE Verification_Loop SHALL give each verification Evidence_Item a deterministic template summary built from the result fields only, record_refs listing every record created by the verification, the mcp_call_id, the verification_id and the Approval_ID.
6. WHEN `run_simulated_verification` returns a result, THE Verification_Loop SHALL append an audit event `verification_executed` with the Approval_ID, verification_id, Verification_Type, params, outcome summary and Evidence_ID, emit a Progress_Event `verification_executed` with payload {proposal_id, approval_id, verification_id, outcomes_summary, evidence_ids}, and route to update_hypotheses.
7. IF `run_simulated_verification` returns a structured error or the MCP call fails, THEN THE Verification_Loop SHALL append an audit event `verification_failed` with the Approval_ID and the error code, emit a Progress_Event `verification_failed` with payload {proposal_id, approval_id, error_code}, register no Evidence_Item, and route to propose_verification, or to finalize_conclusion when the Verification_Round limit is reached.
8. THE Verification_Loop SHALL count every call of `run_simulated_verification` against the case MCP tool call budget.
9. THE Verification_Loop SHALL use no LLM call in execute_verification.

### Requirement 9: Approval Guard

**User Story:** As a plant manager, I want a code-enforced guarantee that nothing runs without human approval, so that the copilot can never act on its own.

#### Acceptance Criteria

1. WHEN execute_verification starts, THE Approval_Guard SHALL check that the Audit_Trail contains a `decision_recorded` event with action approve whose proposal_id, Verification_Type and Normalized_Params equal those of the verification about to run and whose Proposal_Round is the current Proposal_Round.
2. IF the Approval_Guard check fails, THEN THE Verification_Loop SHALL make no MCP call, append an audit event `verification_blocked_no_approval`, and set the Case_Status to FAILED.
3. THE Approval_Guard SHALL allow at most one Verification_Round per approve Decision.
4. THE Approval_Guard SHALL run in code before any MCP call and SHALL NOT depend on LLM output.

### Requirement 10: Hypothesis Update and Judgment Changes

**User Story:** As a quality engineer, I want to see exactly how each hypothesis changed because of the new verification result, so that I can follow and challenge the AI's reasoning.

#### Acceptance Criteria

1. WHEN update_hypotheses runs, THE Verification_Loop SHALL request structured output from the LLM_Client containing the revised Hypotheses in the Hypothesis schema and, for each Hypothesis, a revision entry with hypothesis_id, because (Evidence_IDs) and rationale, passing all Evidence_Items including the new verification Evidence_Item.
2. THE Verification_Loop SHALL apply the Citation_Validator and the Hypothesis_Guardrails to the revised Hypotheses before computing Judgment_Changes.
3. IF a revised Hypothesis keeps the hypothesis_id of a previous Hypothesis but has a different category, THEN THE Verification_Loop SHALL treat the output as invalid and send a repair re-ask.
4. THE Verification_Loop SHALL compute Judgment_Changes in code with a pure function of the Hypotheses before the round, the Hypotheses after the round and the revision entries, producing exactly one Judgment_Change per hypothesis_id in the union of both sets, ordered by hypothesis_id.
5. THE Verification_Loop SHALL set direction to up when after is greater than before, down when after is less than before, unchanged when they are equal, new when the hypothesis_id exists only after the round (before null), and removed when it exists only before the round (after null), using the Evidence_Support order.
6. IF a Judgment_Change has direction up, down or removed and its because does not contain the Evidence_ID of the new verification Evidence_Item, THEN THE Verification_Loop SHALL send a repair re-ask, and IF the condition still holds after the repair re-asks, THEN THE Verification_Loop SHALL restore that Hypothesis to its state before the round, set direction unchanged, append an audit event `judgment_change_unattributed`, and emit a Progress_Event `judgment_change_unattributed` with payload {hypothesis_id}.
7. THE Verification_Loop SHALL require a non-empty rationale for every Judgment_Change whose direction is not unchanged.
8. WHEN a Judgment_Change has a direction other than unchanged, THE Verification_Loop SHALL append an audit event `judgment_changed` containing the full Judgment_Change and the Verification_Round, and emit a Progress_Event `judgment_changed` with payload {change (the full Judgment_Change with the Verification_Round)}.
9. THE Verification_Loop SHALL store the Judgment_Changes of each Verification_Round in the Case_State.
10. IF the LLM output fails validation after the repair re-asks for a reason other than criterion 6, or the LLM provider fails, THEN THE Verification_Loop SHALL set the Case_Status to FAILED_LLM and leave the Hypotheses unchanged.
11. THE Verification_Loop SHALL make at most 3 LLM calls per update_hypotheses invocation.

### Requirement 11: Loop Control and Budgets

**User Story:** As an engine developer, I want the loop to stop at fixed limits, so that every case ends within bounded time and cost.

#### Acceptance Criteria

1. THE Verification_Loop SHALL allow at most 3 Verification_Rounds per Case.
2. WHEN update_hypotheses completes or a verification fails and the Verification_Round counter equals 3, THE Verification_Loop SHALL route to finalize_conclusion with conclude_reason "max_verification_rounds".
3. WHEN propose_verification is entered and the remaining LLM calls are fewer than the Closing_Reserve plus 6 (12 of the case LLM budget of 40, so a new Proposal_Round starts only while at most 28 LLM calls have been used), or the remaining MCP tool calls are fewer than 1, THE Verification_Loop SHALL route to finalize_conclusion with conclude_reason "budget_exhausted" without calling the LLM.
4. WHEN the Verification_Loop routes to finalize_conclusion without a conclude Decision, THE Verification_Loop SHALL append an audit event `loop_auto_concluded` with actor "system" and the conclude_reason.
5. THE Verification_Loop SHALL use the case budgets of the Investigation_Engine (at most 20 MCP tool calls and at most 40 LLM calls per Case, shared with the first segment) and SHALL NOT reset or extend them.
6. IF an LLM call in this segment would exceed the case LLM budget, THEN THE Verification_Loop SHALL NOT make the call.
7. FOR ALL Cases, the number of Verification_Rounds SHALL be at most 3 and the number of Proposal_Rounds SHALL be at most 5.

### Requirement 12: Conclusion Finalization

**User Story:** As a quality engineer, I want the final conclusion to never claim more than the evidence supports, so that I can trust it as decision support.

#### Acceptance Criteria

1. WHEN finalize_conclusion runs, THE Verification_Loop SHALL first compute in code whether the category is forced to INSUFFICIENT_EVIDENCE.
2. THE Verification_Loop SHALL force the category to INSUFFICIENT_EVIDENCE when the highest current support among all current Hypotheses is below MEDIUM, or when two or more current Hypotheses with different categories share that highest support.
3. WHEN the category is not forced, THE Verification_Loop SHALL pass the LLM the set of allowed categories, consisting only of the category of the one current Hypothesis whose support is the highest among all current Hypotheses (and is MEDIUM or HIGH), and SHALL require the LLM to return category, support, statement, cited_evidence and open_questions.
4. WHEN the category is forced, THE Verification_Loop SHALL request only statement, cited_evidence and open_questions from the LLM and SHALL set category INSUFFICIENT_EVIDENCE and support LOW.
5. IF the LLM-returned category is not in the allowed set, or the Conclusion has a category other than INSUFFICIENT_EVIDENCE and zero valid cited Evidence_IDs, THEN THE Verification_Loop SHALL send a repair re-ask, and IF the violation remains after the repair re-asks, THEN THE Verification_Loop SHALL set the Case_Status to FAILED_LLM.
6. IF the LLM-returned support is greater than the Support_Level mapped from the highest support among current Hypotheses with the chosen category, THEN THE Verification_Loop SHALL lower the support to that mapped Support_Level, append an audit event `conclusion_support_capped` with the requested and the applied value, and emit a Progress_Event `conclusion_support_capped` with payload {from (the requested value), to (the applied value)}.
7. THE Verification_Loop SHALL set the Conclusion qualifier in code to "evidence-supported" when support is HIGH and to "suspected" otherwise.
8. THE Verification_Loop SHALL apply the Banned_Wording_Checker to the statement and every open question, and IF a Banned_Phrase remains after the repair re-asks, THEN THE Verification_Loop SHALL store that field as null with the Unavailable_Marker and append an audit event `narrative_unavailable`.
9. THE Verification_Loop SHALL store the conclude_reason ("human_concluded", "max_verification_rounds", "budget_exhausted" or "no valid verification proposal") in the Conclusion.
10. WHEN the Conclusion is stored, THE Verification_Loop SHALL set the Case_Status to CONCLUDING if not already set, append an audit event `conclusion_finalized`, and emit a Progress_Event `conclusion_finalized` with payload {conclusion (the stored Conclusion)}.
11. FOR ALL Case_States, the category of the stored Conclusion SHALL be INSUFFICIENT_EVIDENCE or equal to the category of the current Hypothesis whose support is MEDIUM or HIGH and strictly greater than the support of every current Hypothesis with a different category, and the Conclusion support SHALL be at most the Support_Level mapped from that Hypothesis's support.
12. THE Verification_Loop SHALL make at most 3 LLM calls per finalize_conclusion invocation.

### Requirement 13: Report Structure and Deterministic Sections

**User Story:** As a quality engineer, I want a report with a fixed structure built from the recorded investigation, so that reports are complete and comparable across cases.

#### Acceptance Criteria

1. WHEN generate_report runs for a Case with an anomaly, THE Verification_Loop SHALL build a full-form Report with exactly these 10 sections in this order: (1) Anomaly Overview, (2) Anomaly Metrics, (3) Timeline, (4) Key Evidence, (5) Candidate Causes, (6) Verification Steps Executed, (7) Impact of New Evidence on Judgment, (8) Suspected Affected Product Scope, (9) Recommended Follow-up Actions, (10) Open Questions and Limitations.
2. THE Verification_Loop SHALL build sections 2 to 8 and the non-narrative parts of sections 1 and 10 deterministically from the Case_State, with no LLM call.
3. THE Report section 1 SHALL contain a conclusion block with the Conclusion category, support, qualifier, statement, cited Evidence_IDs and conclude_reason, followed by the LLM-written overview narrative.
4. THE Report section 2 SHALL contain the FAIL_Rate metrics and the Detected_Anomaly_Window from the Anomaly_Detection_Result.
5. THE Report section 3 SHALL contain a production timeline of timestamped Evidence_Items and the Detected_Anomaly_Window bounds ordered by data timestamp, and a separate investigation timeline of `decision_recorded`, `verification_executed`, `verification_failed` and `judgment_changed` audit events ordered by wall-clock timestamp.
6. THE Report section 4 SHALL list every Evidence_Item of the Evidence_Registry ordered by Evidence_ID, with kind, summary and record_refs.
7. THE Report section 5 SHALL list every current Hypothesis with hypothesis_id, category, title, statement, support, supporting Evidence_IDs, contradicting Evidence_IDs and missing_evidence.
8. THE Report section 6 SHALL list every recorded Decision in order with Proposal_Round, action, actor, UTC_Timestamp, note and the Verification_Proposal (if any), and for each Verification_Round the Approval_ID and either the outcome with its Evidence_ID or the error code.
9. THE Report section 7 SHALL list, per Verification_Round, every Judgment_Change with direction other than unchanged as before → after, with because Evidence_IDs and rationale.
10. THE Report section 8 SHALL contain the Suspected_Scope as a sorted SN list and a count, labelled "suspected", built as follows: for TESTER_MEASUREMENT_DRIFT, SNs with a FAIL first EOL test in the Detected_Anomaly_Window on an anomalous EOL_Tester listed in the anomalies of the Anomaly_Detection_Result; for PROCESS_PARAMETER_DEVIATION, SNs with a FAIL first EOL test in the Detected_Anomaly_Window whose recorded ST-20 program_version equals the actual version reported by a MISMATCH process_config_check, or all SNs with a FAIL first EOL test in the Detected_Anomaly_Window when no such verification exists; for every other category, all SNs with a FAIL first EOL test in the Detected_Anomaly_Window, labelled "not attributed to a specific cause".
11. THE Report section 10 SHALL contain the Conclusion open questions, a deterministic list of limitations (the conclude_reason, remaining budgets, the number of `citation_dropped` events, every section showing the Unavailable_Marker, and the statement that the Suspected_Scope is derived only from collected evidence), the LLM-written limitations narrative, and the Disclaimer.
12. WHEN generate_report runs for a Case whose Anomaly_Detection_Result anomaly flag is false, THE Verification_Loop SHALL build a short-form Report containing only sections 1, 2, 4 and 10, built deterministically from the Case_State with no LLM call, where section 1 states that no anomaly was detected and section 10 contains the Disclaimer.
13. WHEN generate_report runs after budget exhaustion before generate_hypotheses completed, THE Verification_Loop SHALL build a full-form Report with Conclusion category INSUFFICIENT_EVIDENCE, support LOW, a null statement and conclude_reason "budget_exhausted", and SHALL show "Not available – investigation stopped: budget exhausted" in every section whose source data does not exist.
14. IF LLM-written text stored in the Case_State (a Hypothesis title or statement, a Verification_Proposal rationale or a Judgment_Change rationale) and shown in a deterministic section contains a Banned_Phrase, THEN THE Verification_Loop SHALL show the Unavailable_Marker in place of that text.
15. THE Verification_Loop SHALL show human-entered Decision notes in section 6 unchanged, marked as human input.

### Requirement 14: Report Narrative Validation

**User Story:** As a quality engineer, I want AI-written report text checked for citations and overclaiming wording, so that the report never states a certified root cause.

#### Acceptance Criteria

1. THE Verification_Loop SHALL obtain the narratives of section 1, section 9 and section 10 in one structured-output LLM call with one field per section, making at most 3 LLM calls per generate_report invocation.
2. THE Verification_Loop SHALL apply the Citation_Validator to every narrative and SHALL accept only Evidence_IDs present in the Evidence_Registry.
3. THE Banned_Wording_Checker SHALL report a match for each Banned_Phrase occurring case-insensitively on word boundaries after whitespace normalization, and SHALL report no match for text without such an occurrence.
4. IF a narrative contains a Banned_Phrase or an unknown Evidence_ID, THEN THE Verification_Loop SHALL send a repair re-ask that names each violation.
5. IF a narrative still contains a Banned_Phrase after the repair re-asks, THEN THE Verification_Loop SHALL show the Unavailable_Marker in that section in place of the narrative, keep the other valid narratives, and append an audit event `narrative_unavailable` naming the section.
6. IF the LLM provider fails during generate_report, THEN THE Verification_Loop SHALL set the Case_Status to FAILED_LLM and SHALL NOT store a Report version.
7. IF the case LLM budget has no call left for the narrative step, THEN THE Verification_Loop SHALL show "Narrative unavailable – LLM budget exhausted" in sections 1, 9 and 10 in place of the narratives.
8. THE Verification_Loop SHALL NOT insert any predefined substitute text in place of an LLM narrative other than the markers defined in criteria 5 and 7.
9. FOR ALL rendered Reports, the Markdown outside human-entered Decision notes SHALL contain no Banned_Phrase.

### Requirement 15: Report Storage and Markdown Rendering

**User Story:** As an API developer, I want reports stored as versioned objects and rendered to Markdown deterministically, so that the same report always looks the same and can be re-rendered later.

#### Acceptance Criteria

1. WHEN generate_report completes, THE Verification_Loop SHALL store the Report in the Report_Store with the case_id, a version number one greater than the highest stored version of the Case (starting at 1), the generation UTC_Timestamp and the form (full or short).
2. THE Report_Store SHALL never modify or delete a stored Report version.
3. THE Report_Renderer SHALL produce Markdown from a stored Report only, with no LLM call, no MCP call and no read of the Case_State.
4. WHEN the Report_Renderer renders the same stored Report twice, THE Report_Renderer SHALL return byte-identical Markdown.
5. THE Report_Renderer SHALL render each section as a level-2 heading "## <number>. <title>" using the section numbers and titles of Requirement 13.
6. THE Report_Renderer SHALL render each Evidence_Item row in section 4 with an anchor `<a id="ev-NNN"></a>`, where `ev-NNN` is the lowercase Evidence_ID.
7. THE Report_Renderer SHALL render every other occurrence of an Evidence_ID as the link `[EV-NNN](#ev-NNN)` pointing to the anchor of that Evidence_ID.
8. FOR ALL rendered Reports, every Evidence_ID occurring in the Markdown SHALL be either an anchor of section 4 or a link whose target anchor exists in section 4.
9. WHEN the Report is stored, THE Verification_Loop SHALL append an audit event `report_generated` with the version, emit a Progress_Event `report_generated` with payload {version}, and set the Case_Status to COMPLETED.

### Requirement 16: Case Status Model

**User Story:** As an API developer, I want a closed set of case statuses with legal transitions, so that clients can rely on the case lifecycle.

#### Acceptance Criteria

1. THE Verification_Loop SHALL represent the Case_Status with exactly the values CREATED, RUNNING, AWAITING_APPROVAL, CONCLUDING, COMPLETED, FAILED_LLM and FAILED.
2. THE Verification_Loop SHALL allow only these Case_Status transitions: CREATED → RUNNING; RUNNING → AWAITING_APPROVAL; AWAITING_APPROVAL → RUNNING; AWAITING_APPROVAL → CONCLUDING; RUNNING → CONCLUDING; CONCLUDING → COMPLETED; RUNNING → FAILED_LLM; CONCLUDING → FAILED_LLM; RUNNING → FAILED; CONCLUDING → FAILED; FAILED_LLM → RUNNING; FAILED_LLM → CONCLUDING.
3. IF a transition not listed in criterion 2 is requested, THEN THE Verification_Loop SHALL refuse it with an error and leave the Case_Status unchanged.
4. THE Verification_Loop SHALL set the Case_Status to RUNNING while propose_verification, execute_verification or update_hypotheses runs, and to CONCLUDING when finalize_conclusion or generate_report is entered.
5. WHEN a valid approve or reject_all Decision is resumed, THE Verification_Loop SHALL set the Case_Status from AWAITING_APPROVAL to RUNNING, and WHEN a valid conclude Decision is resumed, to CONCLUDING.
6. THE Verification_Loop SHALL treat COMPLETED and FAILED as terminal statuses.
7. WHEN the Case_Status changes, THE Verification_Loop SHALL emit a Progress_Event `status_changed` with payload {from, to, reason}, except for the changes to RUNNING made by the Investigation_Engine, for which the Investigation_Engine emits it.
8. IF a non-LLM error prevents a node from completing (other than a verification error handled by Requirement 8 criterion 7), THEN THE Verification_Loop SHALL set the Case_Status to FAILED and append an audit event `case_failed` with the error code.
9. WHEN the Case_Status changes to COMPLETED, FAILED or FAILED_LLM, including a change requested by the Investigation_Engine, THE Verification_Loop SHALL emit exactly one Progress_Event `completed` with payload {final_status} after the `status_changed` event, as the last case event before the investigation-api spec closes the SSE stream.
10. THE Verification_Loop SHALL define the Active_Case_Status values as CREATED, RUNNING, AWAITING_APPROVAL and CONCLUDING, and SHALL treat FAILED_LLM, COMPLETED and FAILED as not active.

### Requirement 17: Retry and Idempotent Resume

**User Story:** As a quality engineer, I want to retry a case after an LLM failure without repeating verifications, so that a temporary provider problem does not cost me my work.

#### Acceptance Criteria

1. THE Verification_Loop SHALL provide a retry function that takes a case_id and accepts it only WHEN the Case_Status is FAILED_LLM.
2. IF retry is requested for a Case whose Case_Status is not FAILED_LLM, THEN THE Verification_Loop SHALL refuse it with error code `retry_not_allowed` and leave the Case unchanged.
3. WHEN retry is accepted, THE Verification_Loop SHALL resume the Investigation_Graph from the last checkpoint of the Case and set the Case_Status to RUNNING, or to CONCLUDING when the resumed node is finalize_conclusion or generate_report.
4. WHEN a Case is resumed, THE Verification_Loop SHALL keep all recorded Decisions, Evidence_Items, Judgment_Changes, audit events and budget counters, and SHALL NOT reset any counter.
5. WHEN execute_verification runs for an Approval_ID that already has a registered verification Evidence_Item, THE Verification_Loop SHALL make no MCP call and SHALL reuse that Evidence_Item.
6. WHEN execute_verification re-calls `run_simulated_verification` with an Approval_ID whose previous call returned a result that was not yet checkpointed, THE Verification_Loop SHALL register at most one Evidence_Item per verification_id.
7. FOR ALL Cases, the number of `verification_executed` audit events SHALL equal the number of distinct Approval_IDs with a successful result.

### Requirement 18: Audit Trail and Progress Events

**User Story:** As a quality auditor, I want every proposal, decision, verification and judgment change recorded in order, so that I can reconstruct how the conclusion was reached.

#### Acceptance Criteria

1. THE Verification_Loop SHALL append audit events to the Audit_Trail only and SHALL never modify or remove an existing audit event.
2. THE Verification_Loop SHALL give each audit event a per-case sequence number, an event type, a wall-clock UTC_Timestamp, an actor (the Decision actor for `decision_recorded`, "system" otherwise) and a details object.
3. THE Verification_Loop SHALL use these audit event types in this segment: `awaiting_approval`, `proposal_rejected_by_validator`, `decision_recorded`, `verification_executed`, `verification_failed`, `verification_blocked_no_approval`, `judgment_changed`, `judgment_change_unattributed`, `loop_auto_concluded`, `conclusion_support_capped`, `conclusion_finalized`, `narrative_unavailable`, `report_generated` and `case_failed`, in addition to the Investigation_Engine case event `citation_dropped`; of these, `verification_blocked_no_approval`, `loop_auto_concluded`, `narrative_unavailable` and `case_failed` are audit-trail-only entries that have no dedicated Case_Event_Catalog type and are emitted as `audit` case events per criterion 8.
4. WHEN an Approval_Payload is created, THE Verification_Loop SHALL append an audit event `awaiting_approval` with the Proposal_Round, the Proposal_IDs and the conclude_option, and emit a Progress_Event `awaiting_approval` with payload {round, proposals, conclude_option, final_round_of_suggestions (the Approval_Payload final_round flag), budgets (the Approval_Payload budgets_remaining)}.
5. THE Verification_Loop SHALL emit its Progress_Events through the Investigation_Engine progress mechanism, so that their sequence numbers continue the per-case sequence of the first segment.
6. THE Verification_Loop SHALL store the Audit_Trail in the checkpointed Case_State, so that it survives a process restart and a retry.
7. THE Verification_Loop SHALL emit exactly these verification-loop-owned case event types of the Case_Event_Catalog: `awaiting_approval`, `proposal_rejected_by_validator`, `decision_recorded`, `verification_executed`, `verification_failed`, `judgment_changed`, `judgment_change_unattributed`, `conclusion_support_capped`, `conclusion_finalized`, `report_generated`, `audit` and `completed`, together with `status_changed` per Requirement 16 criterion 7, each with at least the Case_Event_Catalog payload fields.
8. WHEN the Verification_Loop appends an audit-trail-only entry `verification_blocked_no_approval`, `loop_auto_concluded`, `narrative_unavailable` or `case_failed`, THE Verification_Loop SHALL also emit a Progress_Event of the Case_Event_Catalog type `audit` with payload `{name, actor, details}`, where `name` is the entry's event type, `actor` is "system" and `details` is the details object of the Audit_Trail entry (for example the conclude_reason, the section name or the error code).

### Requirement 19: Deterministic Tests

**User Story:** As a developer, I want deterministic tests for every code-enforced rule, so that the guardrails are verified without calling an LLM.

#### Acceptance Criteria

1. THE Verification_Loop test suite SHALL include tests without the `llm` marker that run without network access and without an LLM, using hand-built Case_States and a stub LLM_Client and a stub MCP client where a node is executed.
2. THE deterministic tests SHALL cover the Proposal_Validator: each rule of Requirement 4 with at least one accepted and one rejected example, including an SN outside the Candidate_SN_List, 6 SNs, an invalid tester_id, an invalid equipment_id, a duplicate of an executed verification, a duplicate of a rejected Verification_Proposal and an unknown hypothesis_id.
3. THE deterministic tests SHALL cover every error code of Requirement 6 and SHALL assert that a rejected Decision leaves the Case_State, Case_Status, Audit_Trail and budgets unchanged.
4. THE deterministic tests SHALL cover the Judgment_Change function for each direction (up, down, unchanged, new, removed) and for the unattributed-change rule of Requirement 10 criterion 6.
5. THE deterministic tests SHALL cover the finalize_conclusion rules: no Hypothesis at MEDIUM or above, a tie at the highest support between Hypotheses with different categories, a single highest Hypothesis at MEDIUM with another at LOW, a disallowed LLM category (including the category of a MEDIUM Hypothesis that is not the highest), support capping, and the qualifier values.
6. THE deterministic tests SHALL build a full-form Report and a short-form Report from hand-built Case_States and assert the section list and order, the Suspected_Scope for each category rule of Requirement 13 criterion 10, byte-identical repeated rendering, and that every Evidence_ID in the Markdown is an existing anchor or a link to one.
7. THE deterministic tests SHALL cover the Banned_Wording_Checker for every Banned_Phrase in mixed case and with extra whitespace, and for non-matches such as "unproven" and the Disclaimer.
8. THE deterministic tests SHALL assert that execute_verification makes zero calls to the stub MCP client when no matching approve Decision exists, when the Decision approved a different Proposal_ID, and when the approve Decision belongs to an earlier Proposal_Round.
9. THE deterministic tests SHALL assert by static inspection that `run_simulated_verification` is called only from the execute_verification module.
10. THE deterministic tests SHALL cover loop limits: routing to finalize_conclusion after 3 Verification_Rounds including failed ones, routing on budget exhaustion per Requirement 11 criterion 3, refusal of a third reject_all with error code `REJECT_LIMIT_REACHED`, the Final_Suggestion_Round flag, and retry without a repeated MCP call per Requirement 17 criterion 5.
11. THE deterministic tests SHALL cover the Case_Status transition table: every legal transition succeeds and a sample of illegal transitions is refused.

### Requirement 20: LLM Integration Tests

**User Story:** As a developer, I want end-to-end tests against the real LLM on the scenario datasets, so that the loop is shown to revise judgments in the expected direction.

#### Acceptance Criteria

1. THE Verification_Loop test suite SHALL mark every test that calls the real LLM provider with the pytest marker `llm`, run it against the default model `deepseek/deepseek-flash`, and answer Approval_Payloads with the Auto_Approve_Policy unless the test states another policy.
2. THE `llm` tests SHALL assert properties of the Case_State, Audit_Trail and Report, and SHALL NOT assert exact LLM-written text.
3. WHEN a Case on Dataset `ds-01` executes a cross_retest or reference_sample_check verification, THE `llm` test SHALL assert that at least one TESTER_MEASUREMENT_DRIFT Hypothesis has a Judgment_Change for that Verification_Round with direction up or after HIGH, whose because contains that verification's Evidence_ID.
4. WHEN a Case on Dataset `ds-02` executes a process_config_check verification, THE `llm` test SHALL assert that at least one PROCESS_PARAMETER_DEVIATION Hypothesis has a Judgment_Change for that Verification_Round with direction up or after HIGH, whose because contains that verification's Evidence_ID.
5. WHEN a Case on Dataset `ds-03` completes, THE `llm` test SHALL assert that the Conclusion category is INSUFFICIENT_EVIDENCE or PRODUCT_MIX_SHIFT with support at most MEDIUM, and is neither TESTER_MEASUREMENT_DRIFT nor PROCESS_PARAMETER_DEVIATION.
6. WHEN an `llm` test answers the first Approval_Payload with reject_all and a note, THE test SHALL assert that no Verification_Proposal of the next Approval_Payload has the Verification_Type and Normalized_Params of a rejected Verification_Proposal.
7. WHEN an `llm` test answers the first Approval_Payload with conclude, THE test SHALL assert that the Case_Status becomes COMPLETED, the conclude_reason is "human_concluded" and a Report version exists.
8. THE `llm` tests SHALL assert for every completed Case that the full-form Report has all 10 sections, that every Evidence_ID in the Report exists in the Evidence_Registry, that the Markdown outside human-entered Decision notes contains no Banned_Phrase, and that the Case used at most 20 MCP tool calls and at most 40 LLM calls.
9. THE `llm` tests SHALL assert that no prompt sent to the LLM_Client during the run contains Ground_Truth content, a Scenario_Registry label or description, or a scenario key.
