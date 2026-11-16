# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent investigates End-of-Line (EOL) quality anomalies on Line A of the fictional Factory Alpha (ST-10 component assembly → ST-20 automatic bolt tightening → ST-30 functional assembly → EOL-A / EOL-B testers) through an Industrial MCP Server over simulated MES, PPM and EOL data. The agent proposes a Next Best Verification, a human approves it, a simulated verification runs, the agent updates its judgment, and a traceable 10-section report is produced.

This spec covers only the frontend single-page application in `frontend/` (the Workspace_UI). It is built with React, TypeScript, Vite, Tailwind CSS, shadcn/ui, ECharts, TanStack Query, react-router and react-markdown, and it renders the line topology with native SVG. The Workspace_UI has two views: the Investigation Workspace (Top_Bar, Factory_Overview_Panel, Investigation_Workspace_Panel, Investigator_Panel) and the Report_View. The audience is international hackathon judges watching a demo of under 3 minutes, so all UI text is in English. The design direction is a professional, dark-themed industrial investigation workbench, desktop-first (1280 px and wider primary, usable at 1024 px).

The Workspace_UI has no fallback mode. When the LLM is not available, every Investigation_Action is disabled with a clear warning, while the factory overview and statistics remain usable. The Workspace_UI never invents data: every displayed value comes from the backend API.

Out of scope:
- A WebGL / Three.js factory view, an evidence relationship graph and investigation replay.
- An LLM provider management UI, Chinese (or any non-English) localization and a mobile layout.
- The backend API, investigation engine, MCP server, simulator, nginx configuration and Docker Compose setup (separate specs).

Assumptions:
- The Workspace_UI uses only the endpoints listed in the investigation-api spec, all under the API base path `/api`. In development, the Vite dev server proxies `/api` to `http://127.0.0.1:18474`. In the Docker Compose demo, nginx serves the built SPA at `http://localhost:18473`, proxies `/api` and falls back to `index.html` for client-side routes.
- The case status model is defined by the verification-loop spec. An Active_Case is a case whose status is CREATED, RUNNING, AWAITING_APPROVAL or CONCLUDING; FAILED_LLM is not an Active_Case status. The backend remains authoritative: the Workspace_UI shows the backend 409 message when its local view is stale.
- The Case_Snapshot returned by `GET /api/cases/{id}` includes `last_event_seq`, the highest persisted event sequence number reflected in it, as defined in the investigation-api spec (Requirement 14 criteria 3 and 7). The Event_Stream_Client uses it to resume the event stream without duplicates or gaps.
- The event types and payloads are those of the Case_Event_Catalog owned by the investigation-api spec. The event stream closes after the `completed` event and stays open while the case is AWAITING_APPROVAL.
- The report response of `GET /api/cases/{id}/report` contains the report Markdown, in which each of the 10 sections starts with a level-2 heading.
- The engine node names delivered in `node_started` and `node_completed` events are mapped to Progress_Stepper steps through one mapping table in the Workspace_UI. A node name that is not in the table does not change the Progress_Stepper.
- The Workspace_UI omits the optional `actor` field in decision requests and lets the backend apply its default (`engineer`).
- The LLM_Indicator polls `GET /api/llm/status` every 30 seconds. The default trend bucket size is 30 minutes, selectable from 15, 30, 60 and 120 minutes; the investigation-api trends endpoint accepts `bucket_minutes` from 15 to 240 with default 30.

Dependencies:
- investigation-api spec: REST endpoints, the SSE event stream `GET /api/cases/{id}/events`, the Case_Event_Catalog, `last_event_seq`, the decision payload rules, the Error_Body format and the case, evidence, hypothesis, proposal, judgment change and report payloads.
- investigation-engine and verification-loop specs: case statuses, budgets per case (20 MCP calls, 40 LLM calls, 3 verification rounds, 2 reject_all decisions) and the report structure.
- delivery-and-evaluation spec: nginx static serving with SPA fallback and the Docker Compose demo at `http://localhost:18473`.

## Glossary

- **Workspace_UI**: The single-page application in `frontend/`, comprising the Investigation Workspace and the Report_View.
- **App_Shell**: The Workspace_UI component that provides routing, the overall page layout, the Toast container and global error boundaries.
- **API_Client**: The single Workspace_UI module that issues all REST requests to paths under `/api` and parses responses and Error_Bodies.
- **Error_Body**: The backend error response body `{"error":{"code","message"}}`.
- **Toast**: A dismissible notification shown for at least 5 seconds that displays an error or confirmation message.
- **Top_Bar**: The header area showing the product name, "Factory Alpha · Line A", the SIMULATION badge, the Case_Selector and the LLM_Indicator.
- **Case_Selector**: The Top_Bar control that lists the cases of the Selected_Dataset and switches the displayed case.
- **LLM_Indicator**: The Top_Bar control that displays the LLM_Status and the model name and triggers an LLM status refresh.
- **LLM_Status**: The `status` value of `GET /api/llm/status` (OK, UNAVAILABLE or MISCONFIGURED), or UNKNOWN while no successful response has been received or when the last request failed.
- **LLM_Banner**: The persistent red banner displayed while the LLM_Status is not OK.
- **Investigation_Action**: Any of the actions Start Investigation, Approve Verification (for any proposal rank), Reject all, Conclude Investigation and Retry.
- **Factory_Overview_Panel**: The left panel containing the Scenario_Selector, the Reset Dataset control, the Line_Topology, tester FAIL_Rate summaries and the data time range.
- **Scenario_Selector**: The control that lists the scenarios returned by `GET /api/scenarios` and sets the Selected_Dataset.
- **Selected_Dataset**: The dataset identified by the `dataset_id` of the scenario currently chosen in the Scenario_Selector.
- **Reset_Dialog**: The confirmation dialog shown before `POST /api/datasets/{id}/reset` is sent.
- **Line_Topology**: The native SVG diagram of ST-10 → ST-20 → ST-30 → EOL-A / EOL-B with equipment status.
- **Equipment_Status**: One of GREEN, ORANGE, RED or GREY, with a reason, as returned by the overview endpoint.
- **Equipment_Drawer**: The side drawer showing the response of `GET /api/datasets/{id}/equipment/{eid}`.
- **Selected_Equipment**: The equipment whose Line_Topology node the user most recently activated while the Equipment_Drawer is open.
- **Related_Evidence**: For an equipment identifier, the evidence items of the displayed case whose `record_refs` or `data` contain a string value equal to that equipment identifier, at any nesting depth.
- **Investigation_Workspace_Panel**: The center panel containing the Anomaly_Card, the Trend_Charts, the Progress_Stepper, the Start_Button and the Evidence_Timeline.
- **Anomaly_Card**: The card summarizing the detected anomaly: tester, baseline and window FAIL_Rate, p-value and detection time.
- **FAIL_Rate**: The share of first (non-retest) EOL tests with result FAIL, as computed and returned by the backend.
- **Trend_Charts**: The ECharts charts for FAIL_Rate per tester, ST-20 angle and torque statistics and reference sample deviations, arranged in tabs.
- **Process_Change_Marker**: A vertical marker in the Trend_Charts at the timestamp of a process change returned by the trends endpoint.
- **Evidence_ID**: An evidence identifier of the form `EV-` followed by three or more digits, for example `EV-001`.
- **Evidence_Chip**: A keyboard-focusable element that displays one Evidence_ID and opens the Evidence_Drawer for it.
- **Evidence_Timeline**: The chronological list of timeline entries of the displayed case.
- **Evidence_Drawer**: The side drawer showing one evidence item from `GET /api/cases/{id}/evidence/{evidence_id}`, including its raw source records.
- **Progress_Stepper**: The step indicator with the steps Load, Detect, Collect, Analyze, Hypotheses, Propose, Approval, Verify, Update and Report.
- **Start_Button**: The "Start Investigation" button in the Investigation_Workspace_Panel.
- **Investigator_Panel**: The right panel titled "AI Investigator", containing the Status_Line, the MCP_Call_List, the Evidence_List, the Hypothesis_Cards, the Decision_Panel, the Judgment_Changes_View and the Conclusion_Card.
- **Status_Line**: The Investigator_Panel line showing the current node, the verification round and the MCP call and LLM call budget usage.
- **MCP_Call_List**: The list of MCP tool calls of the displayed case.
- **Evidence_List**: The Investigator_Panel list of all evidence items of the displayed case, with a source-system filter.
- **Hypothesis_Card**: A card displaying one hypothesis of the displayed case.
- **Support_Badge**: The label "Evidence support: High", "Evidence support: Medium", "Evidence support: Low" or "Evidence support: Insufficient".
- **Decision_Panel**: The Next Best Verification card with the proposal details and the decision buttons.
- **Reject_Dialog**: The dialog in which the user enters the reason for a Reject all decision.
- **Decision_Note_Field**: The optional "Note (optional)" text field of the Decision_Panel whose trimmed content is sent as `note` with an approve or conclude decision.
- **Decision_Pending**: The client state from a successful decision submission until the next `awaiting_approval` event or a change of the case status to CONCLUDING, COMPLETED, FAILED_LLM or FAILED.
- **Judgment_Changes_View**: The Investigator_Panel section listing judgment changes of the displayed case.
- **Conclusion_Card**: The card displaying the final conclusion of the displayed case.
- **Report_View**: The view at route `/cases/:caseId/report` that renders the case report.
- **Case_Snapshot**: The response of `GET /api/cases/{id}`.
- **Case_State**: The client-side state of the displayed case, derived from the latest Case_Snapshot and the events applied after it, including the last applied event sequence number.
- **Active_Case**: A case whose status is CREATED, RUNNING, AWAITING_APPROVAL or CONCLUDING. A FAILED_LLM case is not an Active_Case.
- **Read_Only_Case**: A case whose status is COMPLETED or FAILED, or a FAILED_LLM case for which `POST /api/cases/{id}/retry` returned HTTP 409 with code `DATASET_CHANGED`.
- **Case_Event_Catalog**: The list of event types and payloads delivered by `GET /api/cases/{id}/events`, defined in the investigation-api spec: status_changed, node_started, node_completed, mcp_call, llm_call, anomaly_detected, evidence_added, hypotheses_updated, support_downgraded, citation_dropped, awaiting_approval, proposal_rejected_by_validator, decision_recorded, verification_executed, verification_failed, judgment_changed, judgment_change_unattributed, conclusion_support_capped, conclusion_finalized, report_generated, budget_exhausted, error, completed and audit (24 types). The `audit` type carries `{name, actor, details}` and records audit-trail-only entries emitted by the engine and verification loop, for example `tool_call_rejected`, `analysis_skipped` or `loop_auto_concluded`.
- **Event_Stream_Client**: The Workspace_UI module that consumes `GET /api/cases/{id}/events` through EventSource, reconnects and passes events to the Event_Reducer.
- **Stream_Status**: The Event_Stream_Client connection state: LIVE, RECONNECTING or CLOSED.
- **Event_Reducer**: The pure function that takes a Case_State and one event and returns the next Case_State.
- **Formatter**: The Workspace_UI module that formats timestamps, rates, p-values, durations and enum labels for display.
- **Manual_E2E_Checklist**: The document `frontend/docs/e2e-checklist.md` describing manual end-to-end checks.

## Requirements

### Requirement 1: Application Shell, Routing and Layout

**User Story:** As a hackathon judge, I want one clear workbench layout with stable URLs, so that I can follow the investigation and open a case or its report directly.

#### Acceptance Criteria

1. THE App_Shell SHALL provide the routes `/` (Investigation Workspace without a selected case), `/cases/:caseId` (Investigation Workspace with that case displayed) and `/cases/:caseId/report` (Report_View).
2. IF the browser opens a path that matches none of the routes in criterion 1, THEN THE App_Shell SHALL display the text "Page not found" and a link to `/`.
3. WHILE a viewport width of 1280 px or more is used, THE App_Shell SHALL display the Top_Bar above three side-by-side panels in the order Factory_Overview_Panel (left), Investigation_Workspace_Panel (center) and Investigator_Panel (right).
4. WHILE a viewport width between 1024 px and 1279 px is used, THE App_Shell SHALL keep all three panels reachable without horizontal scrolling of the page, by allowing the Factory_Overview_Panel to collapse behind a toggle button labeled "Factory Overview".
5. WHEN the route `/cases/:caseId` is opened, THE App_Shell SHALL load the Case_Snapshot for that case and set the Selected_Dataset to the `dataset_id` of that case.
6. IF the Case_Snapshot request for the route `/cases/:caseId` returns HTTP 404, THEN THE App_Shell SHALL display "Case {caseId} not found" with a link to `/` instead of the case content.
7. IF a rendering error occurs inside one panel, THEN THE App_Shell SHALL display an error message with a "Reload panel" button inside that panel and SHALL keep the other panels functional.
8. THE App_Shell SHALL use a dark theme with a dark grey base and blue and green accents, and SHALL use red and orange only for anomaly states, warnings and errors.
9. THE Workspace_UI SHALL render only buttons that perform a backend request, a navigation, a dialog or drawer opening, or a disclosure (expand, collapse, tab or filter change), and SHALL NOT render placeholder buttons for unimplemented features.

### Requirement 2: API Client, Loading, Empty and Error States

**User Story:** As a user, I want consistent feedback while data loads or fails, so that I always know whether the screen shows real backend data.

#### Acceptance Criteria

1. THE API_Client SHALL send every REST request to a relative path under `/api` and SHALL perform all server-state fetching through TanStack Query.
2. IF a REST request returns a non-2xx status with an Error_Body, THEN THE API_Client SHALL raise an error carrying the HTTP status, `error.code` and `error.message`.
3. IF a REST request fails with a network error, a timeout or a non-2xx response without a parsable Error_Body, THEN THE API_Client SHALL raise an error with code `NETWORK_ERROR` or `HTTP_<status>` and a message stating that the backend could not be reached or returned an unexpected response.
4. WHEN a user-initiated mutation (start, decision, retry, reset, LLM status refresh) fails, THE Workspace_UI SHALL show a Toast containing the `error.message` from the API_Client error.
5. WHILE the initial data of a panel section is loading, THE Workspace_UI SHALL display a skeleton placeholder of the section's layout in place of the section content, and SHALL NOT display zero values or empty-state text for that section.
6. IF the initial data request of a panel section fails, THEN THE Workspace_UI SHALL display an inline error state in that section containing the error message and a "Retry" button that repeats the request.
7. WHILE no case is displayed, THE Investigation_Workspace_Panel SHALL display the empty state "No investigation yet — select a scenario and press Start Investigation" in place of the Evidence_Timeline, and THE Investigator_Panel SHALL display the empty state "The AI Investigator starts when an investigation is started."
8. WHEN a list section of a displayed case (MCP_Call_List, Evidence_List, Evidence_Timeline, Hypothesis_Cards, Judgment_Changes_View) has loaded with zero items, THE Workspace_UI SHALL display a section-specific empty-state text instead of an empty container.
9. THE Workspace_UI SHALL display only values that are present in API responses or SSE events, and SHALL display the placeholder "—" for a value that the API returns as null or omits.

### Requirement 3: Top Bar and Case Selector

**User Story:** As a judge, I want to see which factory, mode and case I am looking at, so that I understand the context at a glance.

#### Acceptance Criteria

1. THE Top_Bar SHALL display the product name "Factory CSI" with its logo, the text "Factory Alpha · Line A" and a badge with the text "SIMULATION".
2. THE Case_Selector SHALL list the cases returned by `GET /api/cases?dataset_id=` for the Selected_Dataset, ordered by creation time with the newest first, and each entry SHALL show the case id and a text status label.
3. WHEN the user selects a case in the Case_Selector, THE Workspace_UI SHALL navigate to `/cases/:caseId` for that case.
4. WHILE the Selected_Dataset has no cases, THE Case_Selector SHALL display the text "No cases" and SHALL be disabled.
5. WHEN a case is created, a decision is recorded or a case status changes, THE Workspace_UI SHALL refetch the case list of the Selected_Dataset so that the Case_Selector shows the current status.
6. WHEN the Selected_Dataset changes to a dataset that does not own the displayed case, THE Workspace_UI SHALL navigate to `/` and close the event stream of the previously displayed case.
7. THE Top_Bar SHALL display the case id and status label of the displayed case, and SHALL display a Stream_Status indicator with the text "Live", "Reconnecting…" or "Disconnected" while a case is displayed.

### Requirement 4: LLM Status Indicator and LLM-Unavailable Mode

**User Story:** As a judge, I want an explicit LLM status and a clear warning when the LLM is unavailable, so that I am never shown a fake AI investigation.

#### Acceptance Criteria

1. THE LLM_Indicator SHALL display the LLM_Status as a green "LLM OK", red "LLM UNAVAILABLE", orange "LLM MISCONFIGURED" or grey "LLM UNKNOWN" label with a status icon, together with the model name returned by `GET /api/llm/status`.
2. THE LLM_Indicator SHALL show a tooltip containing the provider, the model, the `checked_at` time in UTC and, when present, the `reason`.
3. THE Workspace_UI SHALL request `GET /api/llm/status` on application load and every 30 seconds thereafter.
4. WHEN the user activates the LLM_Indicator, THE Workspace_UI SHALL send `POST /api/llm/status/refresh`, SHALL show a loading indicator on the LLM_Indicator and disable it until the request completes, and SHALL then display the returned status.
5. WHILE the LLM_Status is not OK, THE App_Shell SHALL display the LLM_Banner below the Top_Bar with the text "LLM unavailable – AI investigation is disabled. Overview and statistics remain available.", and the LLM_Banner SHALL NOT be dismissible.
6. WHILE the LLM_Status is not OK, THE Workspace_UI SHALL disable every Investigation_Action and SHALL show on each disabled control a tooltip stating "AI investigation is disabled because the LLM is {status}." with {status} replaced by the LLM_Status.
7. WHILE the LLM_Status is not OK, THE Workspace_UI SHALL keep the Scenario_Selector, Line_Topology, Equipment_Drawer, Anomaly_Card, Trend_Charts, Case_Selector, Evidence_Drawer and Report_View fully functional.
8. WHEN the LLM_Status changes from a non-OK value to OK, THE Workspace_UI SHALL remove the LLM_Banner and re-enable each Investigation_Action whose other enabling conditions are satisfied, without a page reload.
9. WHEN an Investigation_Action request returns HTTP 503 with code `LLM_UNAVAILABLE`, THE Workspace_UI SHALL show a Toast with the returned message and immediately refetch `GET /api/llm/status`.

### Requirement 5: Scenario Selection and Dataset Reset

**User Story:** As a demo operator, I want to choose a scenario and reset its dataset, so that I can run a clean demonstration.

#### Acceptance Criteria

1. THE Scenario_Selector SHALL list every scenario returned by `GET /api/scenarios`, showing its `label` and its `description` as secondary text.
2. IF a scenario has `available` equal to false, THEN THE Scenario_Selector SHALL show it as disabled with the text "Not generated" and SHALL NOT allow it to be selected.
3. WHEN no dataset has been selected yet and the scenario list has loaded, THE Scenario_Selector SHALL select the first scenario with `available` equal to true.
4. THE Workspace_UI SHALL display a scenario `label` only inside the Scenario_Selector, and SHALL NOT display it in the Top_Bar, the Anomaly_Card, the Evidence_Timeline, the Investigator_Panel or the Report_View.
5. WHEN the user activates "Reset Dataset", THE Workspace_UI SHALL open the Reset_Dialog stating the `dataset_id` and that all verification records appended to the dataset will be removed, with the buttons "Cancel" and "Reset Dataset".
6. WHEN the user confirms the Reset_Dialog, THE Workspace_UI SHALL send `POST /api/datasets/{id}/reset`, SHALL disable the confirm button until the response arrives, and on success SHALL close the dialog, show a Toast "Dataset {dataset_id} reset" and refetch the overview, trends and case list of that dataset.
7. WHILE the Selected_Dataset has an Active_Case, THE Workspace_UI SHALL disable "Reset Dataset" with the tooltip "Reset is unavailable while case {case_id} is active."
8. IF `POST /api/datasets/{id}/reset` returns HTTP 409, THEN THE Workspace_UI SHALL keep the Reset_Dialog open, display the returned `error.message` inside it and refetch the case list.
9. WHILE the only case of the Selected_Dataset that is not COMPLETED or FAILED has status FAILED_LLM, THE Workspace_UI SHALL keep "Reset Dataset" enabled, subject to its other enabling conditions.

### Requirement 6: Line Topology

**User Story:** As a judge, I want to see the production line and the status of each piece of equipment, so that I understand where an anomaly appears.

#### Acceptance Criteria

1. THE Line_Topology SHALL render with native SVG one node each for ST-10, ST-20, ST-30, EOL-A and EOL-B, with directed edges ST-10 → ST-20 → ST-30 and a branch from ST-30 to both EOL-A and EOL-B, using the topology returned by `GET /api/datasets/{id}/overview`.
2. THE Line_Topology SHALL show on each node the equipment identifier, the equipment name and the Equipment_Status as both a color and a text label with an icon: GREEN "Normal", ORANGE "Warning", RED "Anomaly", GREY "No data".
3. THE Line_Topology SHALL show the Equipment_Status reason of a node in a tooltip that appears on pointer hover and on keyboard focus.
4. THE Line_Topology SHALL show on the EOL-A and EOL-B nodes the FAIL_Rate of the last 60 minutes and of the full data range as returned by the overview endpoint.
5. THE Factory_Overview_Panel SHALL display the overall FAIL_Rate and the data time range of the Selected_Dataset, with both range limits in UTC.
6. THE Line_Topology SHALL make each node keyboard-focusable with an accessible name of the form "{equipment id} {equipment name}, status {status label}".
7. WHEN a `verification_executed` or `completed` event is applied to the displayed case, THE Workspace_UI SHALL refetch the overview of the Selected_Dataset.
8. IF the overview request fails, THEN THE Factory_Overview_Panel SHALL display the inline error state of Requirement 2 criterion 6 instead of the Line_Topology and SHALL NOT render nodes with assumed statuses.

### Requirement 7: Equipment Detail Drawer and Related Evidence Highlighting

**User Story:** As an investigator, I want to inspect a piece of equipment and see which evidence concerns it, so that I can connect the line view with the investigation.

#### Acceptance Criteria

1. WHEN the user activates a Line_Topology node by click, Enter or Space, THE Workspace_UI SHALL open the Equipment_Drawer for that equipment, set it as the Selected_Equipment and request `GET /api/datasets/{id}/equipment/{eid}`.
2. THE Equipment_Drawer SHALL display the equipment identifier, name, station, Equipment_Status label and reason, and every record list returned by the endpoint as a table with timestamps in UTC.
3. WHEN a record list returned by the equipment endpoint is empty, THE Equipment_Drawer SHALL display "No records" for that list.
4. WHILE a Selected_Equipment exists and a case is displayed, THE Workspace_UI SHALL visually highlight the Related_Evidence entries in the Evidence_Timeline and the Evidence_List and SHALL mark each with the text "Related to {equipment id}".
5. WHILE a Selected_Equipment exists and a case is displayed, THE Equipment_Drawer SHALL list the Evidence_IDs of the Related_Evidence as Evidence_Chips, or the text "No evidence references this equipment yet" when there are none.
6. WHEN the Equipment_Drawer closes by its close button or the Escape key, THE Workspace_UI SHALL clear the Selected_Equipment, remove all highlighting and return keyboard focus to the Line_Topology node that opened it.
7. THE Workspace_UI SHALL compute Related_Evidence with one pure function that takes an equipment identifier and a list of evidence items and returns the matching Evidence_IDs.

### Requirement 8: Anomaly Card and Trend Charts

**User Story:** As a judge, I want to see the detected anomaly and the underlying trends, so that I can judge the statistical signal myself.

#### Acceptance Criteria

1. WHILE a case is displayed, THE Anomaly_Card SHALL display the anomaly of the Case_Snapshot: tester identifier, baseline FAIL_Rate, window FAIL_Rate, p-value and detection time in UTC.
2. WHILE no case is displayed and the overview returns at least one recent anomaly, THE Anomaly_Card SHALL display the most recent overview anomaly with the label "Statistical detection (no investigation yet)".
3. WHILE no case is displayed and the overview returns no recent anomaly, THE Anomaly_Card SHALL display "No anomaly detected in this dataset".
4. THE Trend_Charts SHALL provide three tabs: "FAIL_Rate by tester" (FAIL_Rate per tester per bucket), "ST-20 torque / angle" (mean, p5 and p95 of torque and angle per bucket) and "Reference deviation" (reference sample deviation per tester), all from `GET /api/datasets/{id}/trends`.
5. THE Trend_Charts SHALL request trends with `bucket_minutes` equal to 30 by default and SHALL offer a bucket selector with the values 15, 30, 60 and 120 minutes that refetches the trends when changed.
6. THE Trend_Charts SHALL display every process change returned by the trends endpoint as a Process_Change_Marker on the time axis of each tab, with a tooltip showing the change time in UTC, the equipment, the change type and the old and new values.
7. THE Trend_Charts SHALL distinguish tester series by both color and line style or marker shape and SHALL display a legend naming each series.
8. THE Trend_Charts SHALL label the time axis in UTC and SHALL show FAIL_Rate axis values as percentages.
9. WHEN a tab has no data points in the returned time range, THE Trend_Charts SHALL display "No data in the selected time range" in that tab instead of an empty chart.
10. THE Trend_Charts SHALL give each chart an accessible text description naming the chart, the series and the time range.
11. WHEN a `verification_executed` event is applied to the displayed case, THE Workspace_UI SHALL refetch the trends of the Selected_Dataset.

### Requirement 9: Evidence Timeline and Evidence Drawer

**User Story:** As an investigator, I want a chronological evidence timeline with drill-down to raw records, so that every AI statement is traceable to source data.

#### Acceptance Criteria

1. THE Evidence_Timeline SHALL list the timeline entries of the displayed case in ascending order of `ts`, and SHALL order entries with equal `ts` by their order in the Case_State.
2. THE Evidence_Timeline SHALL show for each entry the time in UTC, a badge with the `source_system` (MES, PPM, EOL, ANALYTICS or VERIFICATION), the description and, when present, an Evidence_Chip for its `evidence_id`.
3. WHEN the user activates an Evidence_Chip anywhere in the Investigation Workspace, THE Workspace_UI SHALL open the Evidence_Drawer and request `GET /api/cases/{id}/evidence/{evidence_id}`.
4. THE Evidence_Drawer SHALL display the Evidence_ID, kind, source system, title, summary, creation time in UTC, the `data` as a key-value view, the MCP call ids, and the raw source records as a table with one column per record field.
5. WHEN the evidence item has no raw source records, THE Evidence_Drawer SHALL display "No raw source records for this evidence (kind: {kind})".
6. IF the evidence request returns HTTP 404, THEN THE Evidence_Drawer SHALL display "Evidence {evidence_id} not found in case {case_id}".
7. WHEN an `evidence_added` event is applied, THE Evidence_Timeline SHALL include the timeline entries of the displayed case that reference the new Evidence_ID without a page reload.
8. WHEN the Evidence_Drawer closes, THE Workspace_UI SHALL return keyboard focus to the Evidence_Chip that opened it.

### Requirement 10: Start Investigation and Progress Stepper

**User Story:** As a demo operator, I want to start an investigation and see its progress through clear steps, so that judges can follow the agent workflow.

#### Acceptance Criteria

1. WHILE the Selected_Dataset has `available` equal to true, the LLM_Status is OK, the Selected_Dataset has no Active_Case and no start request is in flight, THE Start_Button SHALL be enabled; WHILE any of these conditions is unmet, THE Start_Button SHALL be disabled.
2. WHILE the Start_Button is disabled, THE Workspace_UI SHALL show a tooltip on it naming the first unmet condition of criterion 1, using the texts "Select an available scenario", the LLM tooltip of Requirement 4 criterion 6, "Case {case_id} is already active for this dataset" or "Starting…".
3. WHEN the user activates the Start_Button, THE Workspace_UI SHALL send `POST /api/cases` with the `dataset_id` of the Selected_Dataset and, on HTTP 201, SHALL navigate to `/cases/:caseId` for the created case and open its event stream.
4. IF `POST /api/cases` returns HTTP 409, THEN THE Workspace_UI SHALL show a Toast with the returned message and refetch the case list of the Selected_Dataset.
5. THE Progress_Stepper SHALL display the steps Load, Detect, Collect, Analyze, Hypotheses, Propose, Approval, Verify, Update and Report in this order, each with a state of completed, current, pending or failed shown by both an icon and a text label.
6. THE Workspace_UI SHALL derive the Progress_Stepper state only from the Case_State: from `node_started` and `node_completed` node names through one mapping table, `awaiting_approval` (Approval current), `verification_executed` (Verify completed), `judgment_changed` (Update completed) and `completed` with `final_status` COMPLETED (all steps completed).
7. WHEN an `awaiting_approval` event is applied after a `judgment_changed` event, THE Progress_Stepper SHALL mark Approval as current again and display the current verification round as "Round {n}/3".
8. WHEN the case status becomes FAILED_LLM or FAILED, THE Progress_Stepper SHALL mark the current step as failed.
9. WHILE the only case of the Selected_Dataset that is not COMPLETED or FAILED has status FAILED_LLM, THE Workspace_UI SHALL treat the Selected_Dataset as having no Active_Case for criterion 1, so that the Start_Button is enabled when its other conditions hold, while the FAILED_LLM case still offers "Retry" under Requirement 16.

### Requirement 11: Investigator Status Line and MCP Tool-Call List

**User Story:** As a judge, I want to see what the agent is doing and which tools it calls, so that the AI's work is transparent.

#### Acceptance Criteria

1. THE Status_Line SHALL display the current node name, the case status label, "Round {used}/3", "MCP calls {used}/20" and, WHILE the Case_Snapshot budgets provide the LLM call usage, "LLM calls {used}/40", using the values of the Case_State.
2. THE MCP_Call_List SHALL load the existing calls of the displayed case from `GET /api/cases/{id}/mcp-calls` and SHALL append calls received through `mcp_call` events, without duplicate entries for the same call id.
3. THE MCP_Call_List SHALL show for each call the tool name, up to two key arguments truncated to 60 characters, the duration, a text status label and the call id, in ascending order of call time.
4. WHEN the user expands an MCP_Call_List entry, THE MCP_Call_List SHALL display the full arguments as formatted JSON and the result summary.
5. WHILE the MCP_Call_List is scrolled to its newest entry, THE MCP_Call_List SHALL keep the newest entry visible when a new call is appended, and WHILE the user has scrolled away from the newest entry, THE MCP_Call_List SHALL keep the scroll position unchanged.
6. WHEN a `budget_exhausted` event is applied, THE Status_Line SHALL display an orange warning naming the exhausted budget, for example "MCP call budget exhausted (20/20)".
7. WHEN a `citation_dropped` event is applied, THE Investigator_Panel SHALL display a warning entry naming the `item` whose citation was removed and its `invalid_ids`.

### Requirement 12: Evidence List

**User Story:** As an investigator, I want a filterable list of all evidence, so that I can review what the agent collected per source system.

#### Acceptance Criteria

1. THE Evidence_List SHALL list all evidence items of the Case_State in ascending order of Evidence_ID, showing for each the Evidence_Chip, kind, source-system badge, title and summary.
2. THE Evidence_List SHALL provide a source-system filter with the options All, MES, PPM, EOL, ANALYTICS and VERIFICATION, each showing the number of matching items.
3. WHEN the user selects a source-system filter option, THE Evidence_List SHALL display only items whose `source_system` equals that option, or all items for All.
4. WHEN the selected filter matches no evidence item, THE Evidence_List SHALL display "No evidence from {source_system} yet".
5. WHEN an `evidence_added` event is applied, THE Evidence_List SHALL include the new item without a page reload and SHALL update the filter counts.

### Requirement 13: Hypothesis Cards

**User Story:** As a judge, I want each hypothesis shown with its evidence support and gaps, so that I can see why the agent favors or doubts it.

#### Acceptance Criteria

1. THE Investigator_Panel SHALL display one Hypothesis_Card per hypothesis of the Case_State, ordered by support level (HIGH, MEDIUM, LOW, INSUFFICIENT) and then by `hypothesis_id`.
2. THE Hypothesis_Card SHALL display the category as a readable label, the title, the statement and the Support_Badge matching the `support` value.
3. THE Hypothesis_Card SHALL NOT display a percentage, a numeric score or the word "probability" for the support level.
4. THE Hypothesis_Card SHALL display the supporting evidence and the contradicting evidence as two labeled groups of Evidence_Chips, with "None" for an empty group.
5. THE Hypothesis_Card SHALL display the missing evidence as a bulleted list under the heading "Missing evidence", or "None listed" when the list is empty.
6. WHEN a `hypotheses_updated` event is applied, THE Investigator_Panel SHALL replace the displayed hypotheses with the hypotheses of the event without a page reload.

### Requirement 14: Next Best Verification and Decision Actions

**User Story:** As the human approver, I want to review the proposed verification and approve, reject or conclude, so that I stay in control of every verification the AI runs.

#### Acceptance Criteria

1. WHILE the displayed case has status AWAITING_APPROVAL and has pending proposals, THE Decision_Panel SHALL display the rank-1 proposal with its verification type as a readable label, its parameters as labeled values, its rationale, the hypotheses it targets and its cited evidence as Evidence_Chips.
2. THE Decision_Panel SHALL display a parameter that is a list of SNs with the first 10 SNs and a "+{n} more" control that reveals the remaining SNs, and SHALL label the target tester parameter "Target tester".
3. THE Decision_Panel SHALL display the expected outcomes as a table with the columns "If outcome", "Interpretation" and "Hypothesis", showing the interpretation as "supports", "contradicts" or "neutral".
4. WHEN the user activates "Show other suggestions", THE Decision_Panel SHALL reveal the proposals of rank 2 and 3 with the same details as the rank-1 proposal, each with its own "Approve Verification" button, and the control SHALL change to "Hide other suggestions".
5. WHEN the user activates an "Approve Verification" button, THE Workspace_UI SHALL send `POST /api/cases/{id}/decision` with `action` "approve", the `proposal_id` of that pending proposal and, when the trimmed Decision_Note_Field is not empty, that text as `note`.
6. WHEN the user activates "Reject all", THE Workspace_UI SHALL open the Reject_Dialog with a reason text field, a character counter "{n}/500" and the text "Rejections remaining: {remaining} of 2".
7. WHILE the trimmed reason in the Reject_Dialog is empty or longer than 500 characters, THE Reject_Dialog SHALL disable its submit button and display the validation message "A reason is required (max 500 characters)."
8. WHEN the user submits a valid Reject_Dialog, THE Workspace_UI SHALL send `POST /api/cases/{id}/decision` with `action` "reject_all" and the trimmed reason as `note`.
9. WHEN the user activates "Conclude Investigation", THE Workspace_UI SHALL open a confirmation dialog and, on confirmation, SHALL send `POST /api/cases/{id}/decision` with `action` "conclude" and, when the trimmed Decision_Note_Field is not empty, that text as `note`, without a `proposal_id`.
10. WHILE a decision request is in flight or the case is Decision_Pending, THE Decision_Panel SHALL disable all decision buttons and display "Decision submitted — waiting for the AI Investigator", so that one user action sends at most one decision request.
11. IF a decision request fails, THEN THE Workspace_UI SHALL show a Toast with the returned message, leave Decision_Pending and re-enable the decision buttons whose other enabling conditions hold.
12. WHILE all 3 verification rounds are used, THE Decision_Panel SHALL disable every "Approve Verification" button with the tooltip "Verification budget exhausted (3/3)", and WHILE 2 reject_all decisions are used, THE Decision_Panel SHALL disable "Reject all" with the tooltip "Rejection budget exhausted (2/2)".
13. WHILE the displayed case status is not AWAITING_APPROVAL, THE Decision_Panel SHALL NOT display enabled decision buttons and SHALL display the decisions already recorded for the case with their action, proposal, note and time in UTC.
14. WHILE the displayed case status is AWAITING_APPROVAL, THE Decision_Panel SHALL display the Decision_Note_Field with a character counter "{n}/500", and WHILE its trimmed content is longer than 500 characters, THE Decision_Panel SHALL disable every "Approve Verification" button and "Conclude Investigation" and display the validation message "Note must be at most 500 characters."
15. THE Workspace_UI SHALL send a decision request body containing only `action`, `proposal_id` (for approve only), and `note` (required for reject_all, optional for approve and conclude), and SHALL omit `actor` so that the backend applies its default.

### Requirement 15: Judgment Changes and Final Conclusion

**User Story:** As a judge, I want to see how each verification changed the AI's judgment and what it finally concluded, so that the reasoning is auditable.

#### Acceptance Criteria

1. THE Judgment_Changes_View SHALL list every judgment change of the Case_State grouped by verification round, showing the hypothesis title and category, the before Support_Badge, an arrow, the after Support_Badge, the direction as text ("strengthened", "weakened" or "unchanged") with an icon, the "because" Evidence_IDs as Evidence_Chips and the rationale.
2. WHEN a `judgment_changed` event is applied, THE Judgment_Changes_View SHALL include the new change without a page reload.
3. WHEN the Case_State has no judgment changes, THE Judgment_Changes_View SHALL display "No judgment changes yet — they appear after a verification is executed."
4. WHEN the Case_State contains a final conclusion, THE Conclusion_Card SHALL display the category, the Support_Badge, the statement, the cited evidence as Evidence_Chips and the open questions as a bulleted list.
5. THE Conclusion_Card SHALL title a conclusion with support HIGH "Evidence-supported cause", a conclusion with support MEDIUM or LOW "Suspected cause", and a conclusion with category INSUFFICIENT_EVIDENCE "Insufficient evidence for a conclusion".
6. THE Conclusion_Card SHALL NOT use the words "confirmed", "certain", "proven" or "root cause identified".
7. WHILE the report of the displayed case is available, THE Conclusion_Card SHALL display an "Open Report" button that navigates to `/cases/:caseId/report`.

### Requirement 16: Case Lifecycle States, Read-Only Cases and Retry

**User Story:** As a user, I want the workspace to reflect each case state correctly, including failures and finished cases, so that I can recover or review history.

#### Acceptance Criteria

1. WHILE the displayed case status is CREATED, RUNNING or CONCLUDING, THE Investigator_Panel SHALL display an activity indicator with the text "AI Investigator is working…" and the current node name.
2. WHILE the displayed case status is FAILED_LLM, THE Investigator_Panel SHALL display a red error card with the failure reason from the Case_State and a "Retry" button.
3. WHILE the case status is FAILED_LLM, the LLM_Status is OK and no retry request is in flight, THE Investigator_Panel SHALL enable the "Retry" button; WHILE any of these conditions is unmet, THE Investigator_Panel SHALL disable it.
4. WHEN the user activates "Retry", THE Workspace_UI SHALL send `POST /api/cases/{id}/retry` and, on success, SHALL refetch the Case_Snapshot and reopen the event stream.
5. WHILE the displayed case is a Read_Only_Case, THE Workspace_UI SHALL display the label "Read-only — case {status}" in the Investigator_Panel, SHALL NOT render decision or retry buttons, and SHALL display the full audit history: MCP calls, evidence, hypotheses, recorded decisions, judgment changes, `audit` event entries (name, actor, details and timestamp, shown as neutral history entries rather than errors) and, when present, the final conclusion.
6. WHILE the displayed case status is FAILED, THE Investigator_Panel SHALL display the failure message from the Case_State and SHALL NOT offer "Retry".
7. WHEN a Read_Only_Case is opened, THE Workspace_UI SHALL build the Case_State from the Case_Snapshot and the MCP call list, and SHALL NOT keep an event stream open after the `completed` event.
8. IF `POST /api/cases/{id}/retry` returns HTTP 409 with code `DATASET_CHANGED`, THEN THE Workspace_UI SHALL display the returned `error.message` in the FAILED_LLM error card and SHALL treat the case as a Read_Only_Case for the rest of the session, removing the "Retry" button.
9. IF `POST /api/cases/{id}/retry` returns HTTP 409 with code `CONFLICT`, THEN THE Workspace_UI SHALL show a Toast with the returned message, refetch the case list of the Selected_Dataset and keep the "Retry" button subject to criterion 3.

### Requirement 17: Event Stream Client

**User Story:** As a user, I want live updates that survive network interruptions without losing or duplicating events, so that the displayed investigation is always complete and correct.

#### Acceptance Criteria

1. WHEN a case that is not a Read_Only_Case is displayed, THE Event_Stream_Client SHALL open an EventSource on `/api/cases/{id}/events?after={seq}`, where {seq} is the last applied sequence number of the Case_State, which after initial load equals the `last_event_seq` of the Case_Snapshot as defined in the investigation-api spec (Requirement 14 criteria 3 and 7).
2. THE Event_Stream_Client SHALL pass every received event, with its `id` parsed as the integer sequence number, to the Event_Reducer.
3. IF the EventSource connection errors or closes before a `completed` event has been applied, THEN THE Event_Stream_Client SHALL set the Stream_Status to RECONNECTING and reconnect with increasing delays of 1, 2, 4, 8, 16 and then 30 seconds between attempts, resuming with `after` equal to the last applied sequence number.
4. WHEN a reconnection succeeds, THE Event_Stream_Client SHALL set the Stream_Status to LIVE, reset the delay to 1 second and refetch the Case_Snapshot.
5. IF a received event has a sequence number greater than the last applied sequence number plus 1, THEN THE Event_Stream_Client SHALL refetch the Case_Snapshot, replace the Case_State with it and continue with events whose sequence number is greater than the snapshot `last_event_seq`.
6. WHEN a `completed` event is applied, whatever its `final_status` (COMPLETED, FAILED or FAILED_LLM), THE Event_Stream_Client SHALL close the EventSource and set the Stream_Status to CLOSED; WHILE the case status is AWAITING_APPROVAL, THE Event_Stream_Client SHALL keep the EventSource open.
7. WHEN the displayed case changes or the Investigation Workspace unmounts, THE Event_Stream_Client SHALL close the EventSource of the previous case and cancel any pending reconnect timer.
8. WHEN a `status_changed`, `decision_recorded`, `verification_executed`, `report_generated`, `completed` or `error` event is applied, THE Workspace_UI SHALL invalidate the cached Case_Snapshot and the case list of the Selected_Dataset.

### Requirement 18: Event Reducer

**User Story:** As a frontend developer, I want a pure, deterministic event reducer, so that the case state is predictable and fully unit-testable.

#### Acceptance Criteria

1. THE Event_Reducer SHALL be a pure function that returns a new Case_State, does not mutate its inputs, and performs no I/O, timer or random access.
2. IF an event has a sequence number less than or equal to the last applied sequence number of the Case_State, THEN THE Event_Reducer SHALL return the input Case_State unchanged.
3. WHEN the Event_Reducer applies an event, THE Event_Reducer SHALL set the last applied sequence number of the returned Case_State to the event's sequence number.
4. THE Event_Reducer SHALL apply the event types of the Case_Event_Catalog as follows: `status_changed` sets the status to `to` and records `reason`, which is shown as the failure reason when `to` is FAILED_LLM or FAILED; `node_started` sets the current node; `node_completed` marks that node completed with its `duration_ms`; `mcp_call` inserts or updates the call by `mcp_call_id` and updates the MCP calls used; `llm_call` increments the LLM calls used; `anomaly_detected` stores the anomalies and the detected window; `evidence_added` inserts or updates the evidence item by Evidence_ID; `hypotheses_updated` replaces the hypotheses and sets the hypothesis round; `support_downgraded` sets the support of the named hypothesis to `to` and appends a warning with `from`, `to` and `reason`.
5. THE Event_Reducer SHALL apply the event types of the Case_Event_Catalog as follows: `awaiting_approval` sets status AWAITING_APPROVAL, sets the round, replaces the pending proposals, stores `conclude_option`, `final_round_of_suggestions` and `budgets`, and clears Decision_Pending; `proposal_rejected_by_validator` appends a warning with the proposal and `reason`; `decision_recorded` appends the decision, clears the pending proposals and, for action reject_all, increments the reject_all count used; `verification_executed` appends the verification result and updates the verification rounds used; `verification_failed` appends a warning with the `proposal_id` and `error_code`; `judgment_changed` appends the judgment change; `judgment_change_unattributed` appends a warning naming the `hypothesis_id`.
6. THE Event_Reducer SHALL apply the event types of the Case_Event_Catalog as follows: `citation_dropped` appends a warning with the `item` and `invalid_ids`; `conclusion_support_capped` appends a warning with `from` and `to`; `conclusion_finalized` stores the final conclusion; `report_generated` marks the report available with its `version`; `budget_exhausted` marks the named `budget` exhausted; `error` records `code` and `message` as the latest error without changing the status; `completed` sets the status to `final_status` and marks the event stream finished; `audit` appends an entry with `name`, `actor`, `details` and the event timestamp to the case audit history, without recording an error, adding a warning or changing the status.
7. IF an event has a type not listed in criteria 4 to 6, THEN THE Event_Reducer SHALL NOT throw and SHALL return a Case_State whose content equals the input except for the last applied sequence number.
8. FOR ALL sequences of events with distinct sequence numbers, applying them in ascending sequence order and then re-applying any subset of them SHALL produce the same Case_State as applying them once (idempotent deduplication).
9. THE Event_Reducer SHALL accept a snapshot action carrying a Case_Snapshot and SHALL return a Case_State built only from that snapshot, with the last applied sequence number equal to its `last_event_seq`.

### Requirement 19: Report View

**User Story:** As a judge, I want to read, navigate, download and print the investigation report, so that I can review the traceable result outside the live workspace.

#### Acceptance Criteria

1. WHEN the route `/cases/:caseId/report` is opened, THE Report_View SHALL request `GET /api/cases/{id}/report` and render the report Markdown with react-markdown.
2. THE Report_View SHALL NOT render raw HTML contained in the report Markdown and SHALL NOT render links whose URL scheme is not `http`, `https` or an in-page `#` anchor.
3. THE Report_View SHALL display a section navigation listing the titles of the level-2 headings of the report in document order, and WHEN the user activates a navigation entry, THE Report_View SHALL scroll to that section and mark the entry with `aria-current`.
4. IF the report contains a number of level-2 headings other than 10, THEN THE Report_View SHALL still render the report and list all its level-2 headings, and SHALL display the notice "Report structure differs from the expected 10 sections."
5. THE Report_View SHALL give each Evidence_ID entry in the evidence section an anchor with the id `evidence-{Evidence_ID}`, and SHALL render every other occurrence of an Evidence_ID in the report as a link to that anchor, or as an Evidence_Chip that opens the Evidence_Drawer when no such anchor exists.
6. THE Report_View SHALL display, above the report content and on every printed copy, the disclaimer "Simulation only. This report is decision support generated from simulated data and is not a certified root-cause determination."
7. THE Report_View SHALL provide a "Download Markdown" link to `/api/cases/{id}/report.md` and a "Print / Save as PDF" button that calls `window.print()`, and a "Back to workspace" link to `/cases/:caseId`.
8. WHILE the page is printed, THE Report_View SHALL use a light background with dark text, hide the Top_Bar, the panels, the section navigation and all buttons, and start each level-2 section on a new page except the first.
9. IF the report request returns HTTP 404 or 409, THEN THE Report_View SHALL display "Report not available yet — case status: {status}" with the case status from the Case_Snapshot and a link back to the workspace.
10. WHILE the report is loading, THE Report_View SHALL display a skeleton of the section navigation and the report body.

### Requirement 20: Display Formatting

**User Story:** As a judge, I want consistent, unambiguous numbers and times, so that I can compare values across panels and the report.

#### Acceptance Criteria

1. THE Formatter SHALL format every displayed timestamp as `YYYY-MM-DD HH:MM:SS UTC` in UTC, independent of the browser time zone, for example `2026-11-02T10:08:00Z` as `2026-11-02 10:08:00 UTC`.
2. THE Formatter SHALL format every rate given as a fraction between 0 and 1 as a percentage with exactly one decimal place, for example 0.0234 as `2.3%` and 0 as `0.0%`.
3. THE Formatter SHALL format a p-value below 0.001 in scientific notation with two significant digits, for example 0.0000241 as `2.4e-5`, and a p-value of 0.001 or more with three decimal places, for example 0.0123 as `0.012`.
4. THE Formatter SHALL format a duration below 1000 ms as `{n} ms` and a duration of 1000 ms or more as seconds with one decimal place, for example 1234 ms as `1.2 s`.
5. THE Formatter SHALL map enum values to readable labels, for example TESTER_MEASUREMENT_DRIFT to "Tester measurement drift", cross_retest to "Cross retest", reference_sample_check to "Reference sample check" and process_config_check to "Process configuration check".
6. IF the Formatter receives null, undefined, NaN or an unparsable timestamp, THEN THE Formatter SHALL return "—" and SHALL NOT throw.
7. THE Workspace_UI SHALL use the Formatter for every displayed timestamp, rate, p-value, duration and enum label.

### Requirement 21: Visual Design and Accessibility

**User Story:** As any user, including keyboard and low-vision users, I want an accessible, calm interface, so that I can operate every function reliably.

#### Acceptance Criteria

1. THE Workspace_UI SHALL make every interactive control reachable and operable by keyboard in a logical tab order and SHALL show a visible focus indicator on the focused control.
2. THE Workspace_UI SHALL give every icon-only button an `aria-label` describing its action.
3. WHEN a dialog opens, THE Workspace_UI SHALL move focus into the dialog, trap focus inside it, close it on Escape and return focus to the control that opened it.
4. THE Workspace_UI SHALL render normal text with a contrast ratio of at least 4.5:1 and large text, icons and control boundaries with at least 3:1 against their background.
5. THE Workspace_UI SHALL convey every status (equipment status, LLM_Status, case status, Support_Badge, MCP call status, Stream_Status) with a text label or icon in addition to color.
6. THE Workspace_UI SHALL limit animations to transitions of at most 200 ms, and WHILE the user agent reports `prefers-reduced-motion: reduce`, THE Workspace_UI SHALL disable all non-essential animations, including chart animations.
7. WHEN an `awaiting_approval` event is applied, THE Workspace_UI SHALL announce "Verification proposal ready for approval" through a polite ARIA live region.

### Requirement 22: Automated Tests, Static Checks and Manual E2E Checklist

**User Story:** As a maintainer, I want automated tests and checks plus a documented manual run, so that the demo works reliably.

#### Acceptance Criteria

1. THE Workspace_UI SHALL include Vitest unit tests for the Event_Reducer covering every event type of Requirement 18 criteria 4 to 6, ascending-order application, deduplication of repeated sequence numbers, unknown event types, the snapshot action and input immutability.
2. THE Workspace_UI SHALL include tests for the mapping of Equipment_Status, LLM_Status, case status and support level to color and text label, and for the Related_Evidence function.
3. THE Workspace_UI SHALL include Testing Library tests verifying that, WHILE the LLM_Status is UNAVAILABLE, MISCONFIGURED or UNKNOWN, the LLM_Banner is shown and the Start_Button, every "Approve Verification" button, "Reject all", "Conclude Investigation" and "Retry" are disabled.
4. THE Workspace_UI SHALL include Testing Library tests verifying that the Reject_Dialog submit button is disabled for an empty or whitespace-only reason and for a reason longer than 500 characters, and that decision buttons are disabled after a decision is submitted until an `awaiting_approval` event is applied.
5. THE Workspace_UI SHALL include tests for the Formatter covering the examples and edge cases of Requirement 20, run with a non-UTC process time zone.
6. THE Workspace_UI SHALL include Testing Library tests verifying the Report_View section navigation, the absence of rendered raw HTML and the presence of the disclaimer.
7. THE Workspace_UI SHALL provide the npm scripts `typecheck` (`tsc --noEmit`), `lint` (ESLint), `test` (Vitest) and `build` (Vite), and `typecheck`, `lint` and `test` SHALL complete with zero errors.
8. THE Manual_E2E_Checklist SHALL describe step-by-step checks with expected results for scenario A (`ds-01`) and scenario C (`ds-03`) from dataset reset through start, approval, judgment change, conclusion and report print, and a check that the LLM-unavailable state shows the LLM_Banner and disables every Investigation_Action.
