# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot. An LLM agent investigates End-of-Line (EOL) quality anomalies in a fictional automotive-component factory by querying simulated MES, PPM (equipment monitoring) and EOL systems. This spec covers only the first module: the shared data layer (`factory_data/`) and the scenario generator (`simulator/`).

The module generates reproducible datasets for one 8-hour shift on Line A of the fictional Factory Alpha. Each dataset consists of three artifacts with different readers: observable system data (`factory.db`), hidden physical truth (`world_state.json`) and an answer key (`ground_truth.json`). Four datasets are produced: a baseline (`ds-00`) and three anomaly scenarios: Tester Drift (`ds-01`), Manufacturing Process Defect (`ds-02`) and Insufficient Evidence (`ds-03`).

The MCP server, investigation engine, verification loop, API, UI and evaluation harness are separate specs. This spec defines only the interfaces this module provides to them: the shared schema, the world-state models, the scenario registry, the dataset reset capability and support for appending verification-origin records.

All data is fictional. The module uses no real company data, trademarks or internal logs. Real MES/PLC/SCADA integration, physics simulation, real equipment control and multiple factories are out of scope.

Assumptions:
- The default shift runs from 2026-11-02T06:00:00Z to 2026-11-02T14:00:00Z. Scenario timings below are expressed relative to this default.
- The conclusion category "UNKNOWN / INSUFFICIENT_EVIDENCE" is a single enum value named `INSUFFICIENT_EVIDENCE`.
- Only ST-20 produces process measurements (torque and angle). ST-10 and ST-30 produce process steps without measurements.
- Only scenario C elevates the Model B Inherent_Defect_Probability (default 20%, with Model A at a default of 1.5%). The Datasets `ds-00`, `ds-01` and `ds-02` use the baseline Inherent_Defect_Probability for both product models.
- Scenario C changes the model mix and the EOL_Tester routing inside its Anomaly_Window. Outside the Anomaly_Window, scenario C keeps the baseline routing rule, and the full-shift model mix stays within the baseline range.

## Glossary

- **Factory_Data_Package**: The shared Python package `factory_data/` containing table definitions (SQLAlchemy Core), ID formats, UTC time utilities, shared enums, world-state Pydantic models and the Append_Function.
- **Simulator**: The Python package `simulator/` containing the factory configuration, routing, baseline generator, scenario modifiers, artifact writers, scenario registry, reset function and CLI.
- **Schema**: The set of SQLAlchemy Core table definitions in the Factory_Data_Package that describes every table in a Factory_DB.
- **Time_Util**: The single module in the Factory_Data_Package that formats and parses all timestamps.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ` representing an instant in UTC, for example `2026-11-02T10:08:00Z`.
- **ID_Formats**: The module in the Factory_Data_Package that defines, generates and validates identifiers for every entity type.
- **Factory_Config**: The Simulator configuration describing Factory Alpha, Line A, stations, equipment, product models, EOL limits, shift window, product volume and model mix.
- **Station**: One of the manufacturing stations ST-10 (component assembly), ST-20 (automatic bolt tightening) or ST-30 (functional assembly), or the EOL test station.
- **EOL_Tester**: One of the two end-of-line test equipment units, EOL-A or EOL-B.
- **SN**: The unique serial number of one product.
- **Route**: The ordered sequence of processing for one SN: ST-10, then ST-20, then ST-30, then exactly one first EOL test on one EOL_Tester.
- **Baseline_Generator**: The Simulator component that produces a normal-operation dataset from a Factory_Config and a seed.
- **Scenario_Modifier**: A Simulator component that alters the Baseline_Generator behavior to inject one scenario signal (A, B or C).
- **Scenario_Key**: The identifier of a scenario used by the CLI and the Scenario_Registry: `baseline`, `a`, `b` or `c`, mapping to the Dataset_IDs `ds-00`, `ds-01`, `ds-02` and `ds-03`.
- **Dataset**: The set of artifacts produced by one generation run, stored under `data/<dataset_id>/`.
- **Dataset_ID**: An opaque identifier of a Dataset: `ds-00`, `ds-01`, `ds-02` or `ds-03`.
- **Factory_DB**: The SQLite file `data/<dataset_id>/factory.db` containing observable system data only.
- **World_State**: The hidden physical truth of a Dataset: per-SN true measurement values, EOL_Tester bias functions, approved and actual recipe and program configuration, and reference sample availability and tolerance.
- **World_State_File**: The file `data/<dataset_id>/world_state.json`, the serialized World_State.
- **Ground_Truth**: The answer key of a Dataset: expected anomaly equipment, onset window, expected conclusion category, acceptable conclusion set, affected SN set, key signals and expected verification outcomes.
- **Ground_Truth_File**: The file `data/<dataset_id>/ground_truth.json`, the serialized Ground_Truth.
- **Ground_Truth_Writer**: The Simulator module that builds and writes the Ground_Truth_File.
- **True_Value**: The physical `output_voltage` value of one SN, independent of any EOL_Tester.
- **Inherent_Defect_Probability**: For one product model, the probability that the True_Value of an SN of that model lies outside the `output_voltage` limits of the model.
- **Tester_Bias**: The time-dependent additive offset an EOL_Tester applies to a measured value.
- **Measured_Value**: The value recorded in `eol_measurements`, equal to True_Value plus Tester_Bias at the test time plus measurement noise.
- **FAIL_Rate**: For a given set of first (non-retest) historical EOL tests, the number of tests with result FAIL divided by the total number of tests in the set.
- **Anomaly_Window**: The time interval in Ground_Truth during which the scenario signal is present.
- **Drift_Onset**: In scenario A, the instant shift start plus 3 hours (2026-11-02T09:00:00Z for the default shift) from which the EOL-B Tester_Bias increases.
- **Reference_Sample_Check**: A measurement of a known reference sample on an EOL_Tester, recorded in `reference_sample_checks`, where deviation equals measured minus nominal.
- **Reference_Sample_Tolerance**: For one EOL_Tester, the positive number in `output_voltage` units, stored in the World_State, that gives the largest absolute Reference_Sample_Check deviation that still counts as within tolerance.
- **Origin**: A column on `eol_tests` and `reference_sample_checks` with value `historical` (generated) or `verification` (appended later by the verification engine).
- **Append_Function**: The Factory_Data_Package function that the verification engine calls to append verification-origin `eol_tests`, `eol_measurements` and `reference_sample_checks` rows to a Factory_DB. One call appends a batch of up to 5 EOL tests and any reference sample checks in a single transaction.
- **Conclusion_Category**: The shared enum with values TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **Support_Level**: The shared ordered enum with values LOW < MEDIUM < HIGH describing how strongly evidence supports a conclusion.
- **Acceptable_Conclusion**: An entry in Ground_Truth consisting of a Conclusion_Category and a maximum Support_Level. An investigation result with that Conclusion_Category is acceptable when its Support_Level is less than or equal to that maximum.
- **Content_Hash**: A SHA-256 digest computed over a canonical serialization of all Factory_DB table rows ordered by primary key, the World_State_File content and the Ground_Truth_File content.
- **Scenario_Registry**: The Simulator component that lists available Datasets, each with a Dataset_ID, a Scenario_Key, a user-facing label, a user-facing description and a default seed.
- **Reset_Function**: The Simulator function that restores a Dataset to its generated state.
- **CLI**: The command-line entry point `python -m simulator`.
- **Signal_Summary**: The text report the CLI prints after generation.

## Requirements

### Requirement 1: Factory Configuration and Master Data

**User Story:** As a simulator developer, I want a single factory configuration, so that every dataset describes the same fictional factory structure.

#### Acceptance Criteria

1. THE Factory_Config SHALL define exactly one factory, Factory Alpha, containing exactly one line, Line A (Automotive Component Assembly Line).
2. THE Factory_Config SHALL define exactly four Stations on Line A: ST-10 (component assembly), ST-20 (automatic bolt tightening), ST-30 (functional assembly) and the EOL test station.
3. THE Factory_Config SHALL define exactly five equipment units. Each of ST-10, ST-20 and ST-30 SHALL have exactly one unit, the EOL test station SHALL have the EOL_Testers EOL-A and EOL-B, every unit SHALL have an equipment identifier unique within the Factory_Config, and every unit SHALL reference exactly one Station.
4. THE Factory_Config SHALL define exactly two product models, Model A and Model B. Each model SHALL have a unique model identifier and a numeric lower limit and upper limit in volts for the EOL test item `output_voltage`, and the lower limit SHALL be strictly less than the upper limit.
5. WHEN a Dataset is generated, THE Simulator SHALL write exactly 4 rows to the `stations` table, 5 rows to the `equipment` table and 2 rows to the `product_models` table of the Factory_DB, with identifiers, names, Station references and `output_voltage` limits equal to the values in the Factory_Config.
6. WHEN the Datasets `ds-00`, `ds-01`, `ds-02` and `ds-03` are generated with the same Factory_Config, THE Simulator SHALL produce identical row contents in the `stations`, `equipment` and `product_models` tables of all four Factory_DB files.
7. IF the Factory_Config is missing any Station, equipment unit or product model listed in criteria 2 to 4, or defines a product model whose `output_voltage` lower limit is greater than or equal to its upper limit, THEN THE Simulator SHALL reject the configuration with a descriptive error that names the invalid entry, before it writes any file under `data/<dataset_id>/`.
8. THE Factory_Config SHALL contain only the factory, line, Station, EOL_Tester and product model names defined in criteria 1 to 4, plus identifiers generated by the Simulator, and SHALL contain no real company name, trademark or real equipment vendor name.

### Requirement 2: Shared Schema

**User Story:** As a developer of the later MCP server, I want one shared table definition, so that the generator and all readers agree on the data layout.

#### Acceptance Criteria

1. THE Factory_Data_Package SHALL define the Schema using SQLAlchemy Core with exactly twelve tables and no others: `stations`, `equipment`, `product_models`, `production_orders`, `products`, `process_steps`, `process_measurements`, `equipment_events`, `process_changes`, `eol_tests`, `eol_measurements` and `reference_sample_checks`.
2. THE Schema SHALL define `production_orders` with columns order_id, model_id, qty and start_ts.
3. THE Schema SHALL define `products` with columns sn, order_id, model_id, material_lot and created_ts.
4. THE Schema SHALL define `process_steps` with columns step_id, sn, station_id, equipment_id, start_ts, end_ts, recipe_version and result.
5. THE Schema SHALL define `process_measurements` with columns meas_id, step_id, sn, equipment_id, ts, parameter (allowed values: torque, angle), value, unit and program_version.
6. THE Schema SHALL define `equipment_events` with columns event_id, equipment_id, ts, event_type (allowed values: state, alarm, maintenance, calibration), severity and details_json.
7. THE Schema SHALL define `process_changes` with columns change_id, equipment_id, ts, change_type, old_value, new_value and changed_by.
8. THE Schema SHALL define `eol_tests` with columns test_id, sn, tester_id, ts, model_id, result (allowed values: PASS, FAIL), failure_code (nullable), is_retest (boolean), retest_of (nullable) and origin (allowed values: historical, verification).
9. THE Schema SHALL define `eol_measurements` with columns meas_id, test_id, test_item, value, lower_limit, upper_limit and result (allowed values: PASS, FAIL).
10. THE Schema SHALL define `reference_sample_checks` with columns check_id, tester_id, ts, sample_id, test_item, nominal, measured, deviation, result (allowed values: PASS, FAIL) and origin (allowed values: historical, verification).
11. THE Schema SHALL declare a foreign key for every column that references another table, with these targets: sn → `products`.sn; station_id → `stations`.station_id; equipment_id and tester_id → `equipment`.equipment_id; model_id → `product_models`.model_id; order_id → `production_orders`.order_id; step_id → `process_steps`.step_id; test_id and retest_of → `eol_tests`.test_id. Every foreign key column except retest_of SHALL be non-nullable.
12. THE Schema SHALL declare every timestamp column as a text column that holds a UTC_Timestamp. The timestamp columns are `production_orders`.start_ts, `products`.created_ts, `process_steps`.start_ts and end_ts, and the ts column of `process_measurements`, `equipment_events`, `process_changes`, `eol_tests` and `reference_sample_checks`.
13. THE Schema SHALL define `stations` with columns station_id and name, `equipment` with columns equipment_id, station_id and name, and `product_models` with columns model_id, name, and the lower limit and upper limit for the EOL test item `output_voltage`.
14. THE Schema SHALL declare the first column listed for each table in criteria 2 to 10 and 13 as that table's single-column primary key.
15. IF a row inserted into a Factory_DB table has a value outside the allowed set for `process_measurements`.parameter, `equipment_events`.event_type, any result column of `eol_tests`, `eol_measurements` or `reference_sample_checks`, or any origin column, THEN THE Factory_DB SHALL reject the insert with an error and leave the table's existing rows unchanged.

### Requirement 3: Identifier Formats

**User Story:** As a developer of downstream modules, I want documented identifier formats, so that I can validate and join identifiers across systems.

#### Acceptance Criteria

1. THE ID_Formats SHALL define one documented format for each identifier type: order_id, sn, step_id, meas_id, event_id, change_id, test_id and check_id. Each format SHALL allow only ASCII uppercase letters, digits and hyphens, with a length of 1 to 32 characters.
2. THE ID_Formats SHALL define the formats so that they are mutually exclusive: a string the validation function accepts for one identifier type is rejected for every other identifier type.
3. THE ID_Formats SHALL use one meas_id format for both `process_measurements` and `eol_measurements`.
4. THE ID_Formats SHALL provide a validation function that takes an identifier type and a value. It SHALL return true when the value is a string matching that type's format, and false otherwise. Values that SHALL return false include an empty string, a string longer than 32 characters, a string with leading or trailing whitespace, and a value that is not a string.
5. IF the validation function receives an identifier type outside order_id, sn, step_id, meas_id, event_id, change_id, test_id and check_id, THEN THE ID_Formats SHALL raise an error indicating an unknown identifier type and SHALL NOT return true or false.
6. WHEN the Simulator generates an identifier of a given type, THE ID_Formats SHALL produce a string that the validation function accepts for that type.
7. WHEN the Simulator generates a Dataset, THE Simulator SHALL assign identifiers so that every identifier is unique within its type across the whole Factory_DB. For meas_id, uniqueness SHALL hold across `process_measurements` and `eol_measurements` together.
8. WHEN the Simulator generates a Dataset twice from the same Factory_Config and seed, THE Simulator SHALL assign the same identifier values to the same records in both runs.
9. THE ID_Formats SHALL produce identifiers that contain none of the following, compared case-insensitively as substrings: a scenario name, a Scenario_Registry label, a Conclusion_Category value, a Ground_Truth field name, a Ground_Truth key signal text, a Ground_Truth-only verification outcome value (WITHIN_TOLERANCE, OUT_OF_TOLERANCE, UNAVAILABLE, MATCH or MISMATCH), or the Anomaly_Window start or end UTC_Timestamp. SN values and equipment identifiers listed in a Ground_Truth are excluded from this check, because they are observable identifiers that also appear in the Factory_DB. This list is the same as the list in Requirement 10 criterion 3, plus the Anomaly_Window timestamps.
10. THE ID_Formats SHALL use the same format and generation rule for records inside and outside the Anomaly_Window, and for SNs inside and outside the Ground_Truth affected SN set.
11. THE ID_Formats SHALL provide a function that generates test_id, meas_id and check_id values for verification-origin records. Each value SHALL be accepted by the validation function for its type. Each value SHALL also differ from every identifier of the same type already in the Factory_DB, including those of previously appended verification-origin records.

### Requirement 4: UTC Time Utilities

**User Story:** As a developer, I want a single time utility, so that all timestamps use one consistent UTC representation.

#### Acceptance Criteria

1. WHEN the Time_Util formats a timezone-aware datetime, THE Time_Util SHALL convert the datetime to UTC and return a 20-character UTC_Timestamp in the form `YYYY-MM-DDTHH:MM:SSZ` (for example, a datetime of 2026-11-02 15:08:00 at offset +05:00 SHALL format as `2026-11-02T10:08:00Z`).
2. WHEN the Time_Util parses a string that exactly matches the UTC_Timestamp form `YYYY-MM-DDTHH:MM:SSZ` and denotes a valid calendar date and time, THE Time_Util SHALL return a timezone-aware datetime whose timezone is UTC and whose microsecond component is 0.
3. IF the Time_Util is asked to format a naive datetime (a datetime without timezone information), THEN THE Time_Util SHALL raise a ValueError whose message states that a timezone-aware datetime is required, and SHALL return no UTC_Timestamp.
4. THE Time_Util SHALL satisfy two round-trip properties: (a) for every timezone-aware datetime with a microsecond component of 0 whose UTC instant falls in years 1000 through 9999, parsing the formatted result SHALL return a datetime equal to the input; (b) for every valid UTC_Timestamp string, formatting the parsed result SHALL return a string identical to the input.
5. WHEN the Simulator writes a timestamp value to a Factory_DB, a World_State_File or a Ground_Truth_File, THE Simulator SHALL produce that value with the Time_Util format function, so that every timestamp value in those artifacts matches the UTC_Timestamp form.
6. WHEN the Time_Util formats a timezone-aware datetime with a nonzero microsecond component, THE Time_Util SHALL drop the fractional seconds (truncate toward the earlier whole second) and SHALL return a UTC_Timestamp without a fractional part.
7. IF the Time_Util parse function receives a value that is not a string, or a string that deviates from the UTC_Timestamp form, including a numeric offset such as `+00:00`, a lowercase `z`, a missing `Z`, fractional seconds, leading or trailing whitespace, a date without a time, or out-of-range calendar values such as month 13, `2026-02-30` or hour 24, THEN THE Time_Util SHALL raise a ValueError whose message includes the rejected input and the expected form `YYYY-MM-DDTHH:MM:SSZ`, and SHALL return no datetime.
8. WHEN the Simulator reads a timestamp from the Factory_Config or from an existing Dataset artifact, THE Simulator SHALL convert it to a datetime with the Time_Util parse function.

### Requirement 5: Product Routing

**User Story:** As an investigator agent developer, I want every product to follow the defined line route, so that process history is consistent across systems.

#### Acceptance Criteria

1. WHEN the Baseline_Generator creates a product, THE Baseline_Generator SHALL write one `products` row with a non-null sn, order_id, model_id, material_lot and created_ts, where the sn passes the ID_Formats validation for sn, no other `products` row in the same Factory_DB has the same sn, the model_id is one of the product models defined in the Factory_Config, and the order_id references a `production_orders` row whose model_id equals the product's model_id.
2. THE Baseline_Generator SHALL create exactly three `process_steps` rows for every SN, one with station_id ST-10, one with station_id ST-20 and one with station_id ST-30, and no process steps at any other station, ordered by start_ts as ST-10, then ST-20, then ST-30.
3. THE Baseline_Generator SHALL create exactly one `eol_tests` row for every SN with is_retest false and origin `historical` (the first EOL test), with a tester_id of either EOL-A or EOL-B.
4. WHILE generating a Dataset whose Scenario_Modifier does not alter EOL_Tester assignment, including the baseline Dataset `ds-00`, THE Baseline_Generator SHALL assign first EOL tests so that, for each product model, the number of first historical EOL tests on each EOL_Tester divided by the total number of first historical EOL tests of that model is between 40% and 60% inclusive.
5. THE Baseline_Generator SHALL write exactly one `process_measurements` row with parameter torque (unit N·m) and exactly one row with parameter angle (unit degrees) for every ST-20 process step, each with the same sn and equipment_id as the referenced step and a program_version equal to the new_value of the latest program-version `process_changes` row for that ST-20 equipment with ts earlier than or equal to the measurement ts, or equal to the initial program version from the Factory_Config if no such row exists.
6. THE Baseline_Generator SHALL write no `process_measurements` rows that reference an ST-10 or ST-30 process step.
7. THE Baseline_Generator SHALL set the recipe_version of each process step equal to the new_value of the latest recipe-version `process_changes` row for the step's equipment with ts earlier than or equal to the step start_ts, or equal to the initial recipe version from the Factory_Config for that equipment if no such row exists.

### Requirement 6: Timestamp Consistency

**User Story:** As an investigator agent developer, I want monotonic and consistent timestamps, so that time-based joins and window queries are reliable.

#### Acceptance Criteria

1. THE Simulator SHALL set the start_ts of every production order earlier than or equal to the created_ts of every product that references that order_id, comparing UTC_Timestamp values at whole-second precision.
2. THE Simulator SHALL set the created_ts of each product earlier than or equal to the start_ts of the ST-10 process step of the same SN.
3. THE Simulator SHALL set the start_ts of each process step at least 1 second earlier than the end_ts of the same step.
4. THE Simulator SHALL set the start_ts of the ST-20 process step later than or equal to the ST-10 end_ts of the same SN, and the start_ts of the ST-30 process step later than or equal to the ST-20 end_ts of the same SN.
5. THE Simulator SHALL set the ts of the first (non-retest) EOL test of each SN later than or equal to the ST-30 end_ts of the same SN.
6. THE Simulator SHALL set the ts of each retest at least 1 second later than the ts of the EOL test referenced by its retest_of value.
7. THE Simulator SHALL set the ts of each process measurement later than or equal to the start_ts and earlier than or equal to the end_ts of the process step referenced by its step_id.
8. THE Simulator SHALL set every timestamp column value in every historical record to a value later than or equal to the configured shift start and earlier than or equal to the configured shift end (by default 2026-11-02T06:00:00Z to 2026-11-02T14:00:00Z). Historical records are all rows in `production_orders`, `products`, `process_steps`, `process_measurements`, `equipment_events` and `process_changes`, plus the rows in `eol_tests` and `reference_sample_checks` whose Origin is `historical`.
9. IF the configured shift end is not later than the configured shift start, THEN THE Simulator SHALL reject the Factory_Config with a descriptive error that identifies the shift window, before it writes any Dataset artifact.
10. IF a generated record violates any of criteria 1 to 8 before the Dataset artifacts are written, THEN THE Simulator SHALL stop generation with a descriptive error that identifies the violated constraint and the ID of at least one offending record, and SHALL not write a Factory_DB, World_State_File or Ground_Truth_File for that run.

### Requirement 7: Baseline Generation Model

**User Story:** As a scenario designer, I want a realistic normal-operation baseline, so that injected anomalies stand out against plausible background data.

#### Acceptance Criteria

1. THE Baseline_Generator SHALL generate exactly one shift of 8 hours, using the shift window in the Factory_Config, and SHALL create exactly the configured product count of SNs (an integer from 500 to 1000 inclusive, default 800).
2. IF the configured product count is not an integer, is lower than 500 or is higher than 1000, THEN THE Simulator SHALL reject the configuration with an error that names the product count parameter and the allowed range 500 to 1000, and SHALL write no Dataset artifacts.
3. THE Baseline_Generator SHALL assign exactly one product model to every SN so that, over the full shift, Model A is assigned to a share of SNs between 65% and 75% inclusive and Model B to every remaining SN. The Model A target share is configurable and defaults to 70%. This range applies to the full shift: a Scenario_Modifier that varies the model mix within parts of the shift (Requirement 16 criterion 9) SHALL keep the full-shift Model A share within this range.
4. THE Baseline_Generator SHALL compute each True_Value as a deterministic function of the ST-20 tightening angle deviation of the SN, plus zero-mean product-level noise. The angle deviation is the recorded ST-20 angle measurement of the SN minus the nominal tightening angle in the Factory_Config. When both the angle deviation and the noise are zero, the function SHALL return the midpoint of the `output_voltage` lower and upper limits of the SN's product model.
5. THE Baseline_Generator SHALL compute each Measured_Value of `output_voltage` as the True_Value, plus the Tester_Bias of the EOL_Tester at the test ts, plus zero-mean measurement noise. It SHALL record that value in exactly one `eol_measurements` row per EOL test, with test_item `output_voltage` and with lower_limit and upper_limit equal to the limits of the SN's product model.
6. IF a Measured_Value is strictly below the lower limit or strictly above the upper limit of the product model, THEN THE Baseline_Generator SHALL set the EOL measurement result to FAIL.
7. WHEN a Measured_Value is greater than or equal to the lower limit and less than or equal to the upper limit of the product model, THE Baseline_Generator SHALL set the EOL measurement result to PASS.
8. IF at least one `eol_measurements` row of an EOL test has result FAIL, THEN THE Baseline_Generator SHALL set the EOL test result to FAIL and set failure_code to a non-empty value that identifies the failing test item.
9. WHEN every `eol_measurements` row of an EOL test has result PASS, THE Baseline_Generator SHALL set the EOL test result to PASS and set failure_code to null.
10. WHEN the baseline Dataset `ds-00` is generated with the default Factory_Config and the Scenario_Registry default seed, THE Baseline_Generator SHALL produce a FAIL_Rate between 0.5% and 4.0% inclusive for each EOL_Tester.
11. WHILE no Scenario_Modifier removes Reference_Sample_Checks (Requirement 16 criterion 5 removes the checks inside the scenario C Anomaly_Window), THE Baseline_Generator SHALL record exactly 8 historical Reference_Sample_Checks for the `output_voltage` test item on each EOL_Tester, one per hour of the shift. Check number k (k = 0 to 7) SHALL have a ts at or after shift start + k hours and before shift start + (k + 1) hours. Each check SHALL have a deviation equal to measured minus nominal and a result that states whether the absolute deviation is within the Reference_Sample_Tolerance of that EOL_Tester. Every check that a Scenario_Modifier keeps SHALL follow the same ts, deviation and result rules.
12. WHEN the shift starts, THE Baseline_Generator SHALL record exactly one `equipment_events` row with event_type state and ts equal to the shift start for each of the 5 equipment units (the ST-10, ST-20 and ST-30 equipment, EOL-A and EOL-B). Each row SHALL have details_json indicating the equipment is in production-ready operation.
13. IF the configured Model A target share is below 65% or above 75%, THEN THE Simulator SHALL reject the configuration with an error that names the model mix parameter and the allowed range 65% to 75%, and SHALL write no Dataset artifacts.
14. WHILE no Scenario_Modifier alters the Tester_Bias of an EOL_Tester, THE Baseline_Generator SHALL keep the absolute Tester_Bias of that EOL_Tester less than or equal to its Reference_Sample_Tolerance at every UTC_Timestamp in the shift window, so that every Reference_Sample_Check in `ds-00` has a result indicating within tolerance.

### Requirement 8: Reproducibility

**User Story:** As a test author, I want deterministic generation, so that tests and evaluations are repeatable.

#### Acceptance Criteria

1. WHEN two Datasets are generated with the same scenario, seed and Factory_Config, THE Simulator SHALL produce Datasets with identical Content_Hash values, including when the two generations run in separate processes, at different wall-clock times and into different output directories.
2. WHEN two Datasets are generated with the same scenario and Factory_Config but different seeds, THE Simulator SHALL produce Datasets with different Content_Hash values, for each of the four scenarios (baseline, a, b and c).
3. THE Simulator SHALL derive every random value in the Factory_DB, World_State_File and Ground_Truth_File solely from the provided seed, so that no artifact content depends on wall-clock time, process-global random state, process ID, host name or the output directory path.
4. THE Simulator SHALL derive every UTC_Timestamp written to the Factory_DB, World_State_File and Ground_Truth_File during generation from the configured shift window start and end, independent of wall-clock time at generation.
5. THE Simulator SHALL provide a function that accepts a Dataset directory path, returns the Content_Hash of that Dataset as a 64-character lowercase hexadecimal string, modifies no file in the directory, and returns the same value on repeated calls against an unmodified directory.
6. IF the Content_Hash function is called with a path that does not exist or that lacks any of `factory.db`, `world_state.json` or `ground_truth.json`, THEN THE Simulator SHALL raise a descriptive error identifying the missing path or artifact and return no hash value.
7. IF the Simulator receives a seed that is not an integer from 0 to 4,294,967,295 inclusive, THEN THE Simulator SHALL raise a descriptive error indicating the invalid seed, write no artifacts and leave any existing Dataset files unchanged.

### Requirement 9: Referential Integrity

**User Story:** As a developer of the MCP server, I want referential integrity in the Factory_DB, so that joins across MES, PPM and EOL data never produce orphan records.

#### Acceptance Criteria

1. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB in which every non-null value in a foreign key column declared by the Schema references an existing row in the referenced table, such that running the SQLite foreign key check on the Factory_DB reports zero violations.
2. WHEN a Dataset is generated, THE Simulator SHALL set the model_id of each `products` row equal to the model_id of the `production_orders` row referenced by its order_id, and SHALL set the model_id of each `eol_tests` row equal to the model_id of the `products` row referenced by its sn.
3. WHEN a Dataset is generated, THE Simulator SHALL set the equipment_id of each `process_steps` row to an equipment unit that the Factory_Config assigns to the station_id of the same row.
4. WHEN a Dataset is generated, THE Simulator SHALL set the retest_of value of each `eol_tests` row with is_retest true to the test_id of an `eol_tests` row that has the same sn and a strictly earlier ts, and SHALL set retest_of to null for every `eol_tests` row with is_retest false.
5. WHEN the Simulator, including the Reset_Function, opens a connection to a Factory_DB, THE Simulator SHALL enable SQLite foreign key enforcement on that connection before it executes any read or write statement, so that querying the connection's foreign key setting returns enabled.
6. WHEN a Dataset is generated, THE Simulator SHALL set the sn and equipment_id of each `process_measurements` row equal to the sn and equipment_id of the `process_steps` row referenced by its step_id.
7. WHEN a Dataset is generated, THE Simulator SHALL set the tester_id of every `eol_tests` row and every `reference_sample_checks` row to EOL-A or EOL-B.
8. IF inserting a generated row into a Factory_DB violates a foreign key constraint, THEN THE Simulator SHALL stop generating that Dataset, raise an error that names the table of the rejected row, and print no Signal_Summary for that Dataset.

### Requirement 10: Information Isolation of Artifacts

**User Story:** As the system designer, I want observable data, hidden truth and answer key separated, so that the investigator agent cannot see the answer.

#### Acceptance Criteria

1. WHEN a Dataset is generated, THE Simulator SHALL write exactly three files under `data/<dataset_id>/`, named `factory.db` (the Factory_DB), `world_state.json` (the World_State_File) and `ground_truth.json` (the Ground_Truth_File). After generation finishes, that directory SHALL contain no other files, no subdirectories and no SQLite journal or write-ahead-log files.
2. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB whose tables and columns exactly match the Schema, with no additional tables, views, triggers or columns. The set of table names and column names SHALL be identical across `ds-00`, `ds-01`, `ds-02` and `ds-03`.
3. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB in which no table name, column name or text value meets any of the following conditions, using case-insensitive comparison. Text values include the content of `details_json` values.
   - It contains a scenario name or a Scenario_Registry label as a substring. Scenario names include "Tester Drift", "Manufacturing Process Defect" and "Insufficient Evidence". The single-letter scenario identifiers A, B and C are excluded from this check.
   - It contains a Conclusion_Category value as a substring.
   - It contains the substring `world_state` or `ground_truth`.
   - It is exactly equal to a Ground_Truth field name.
   - It contains a Ground_Truth key signal text or a Ground_Truth-only verification outcome value (WITHIN_TOLERANCE, OUT_OF_TOLERANCE, UNAVAILABLE, MATCH or MISMATCH) as a substring.
   Ground_Truth values that the Factory_DB also records as observable data are excluded from this check: SN values, equipment identifiers, UTC_Timestamps and the PASS and FAIL result values. Criterion 6 covers the Anomaly_Window, and Requirement 3 criterion 9 applies the same list to identifiers.
4. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB that contains no table or column storing a True_Value, a Tester_Bias value or a parameter of a Tester_Bias function. Every `value` in `eol_measurements` SHALL be the Measured_Value.
5. WHEN a Dataset is generated, THE Simulator SHALL name its directory with exactly one of the Dataset_ID values `ds-00`, `ds-01`, `ds-02` or `ds-03`, with no prefix, suffix, scenario name or scenario label.
6. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB that contains no table, column or row value marking an SN as affected or unaffected by the scenario signal. It SHALL also contain no table or column that stores the Anomaly_Window start or end as a dedicated value.
7. WHEN a Dataset is generated, THE Simulator SHALL write a Factory_DB that contains no table, column or row value designating any recipe version or program version as approved. Recipe and program versions MAY appear as old_value and new_value in `process_changes`.
8. WHEN a Dataset is generated, THE Simulator SHALL set Origin to `historical` on every row of `eol_tests` and `reference_sample_checks` in the Factory_DB, and SHALL write zero rows with Origin `verification`.

### Requirement 11: World State Model

**User Story:** As a developer of the later verification engine, I want a typed hidden world state, so that verification outcomes can be computed from physical truth.

#### Acceptance Criteria

1. THE Factory_Data_Package SHALL define the World_State as Pydantic models in a dedicated submodule that can be imported without importing the Simulator package.
2. THE World_State SHALL contain exactly one True_Value for each SN in the `products` table of the Factory_DB of the same Dataset, and SHALL contain no True_Value for an SN that is absent from that table.
3. THE World_State SHALL contain exactly one Tester_Bias function definition for each of EOL-A and EOL-B. Each definition SHALL consist of a constant base offset, an optional onset UTC_Timestamp and a slope in `output_voltage` units per hour.
4. THE World_State SHALL contain one approved recipe version and one approved program version for each of the three Station equipment units of ST-10, ST-20 and ST-30. Each version SHALL be a non-empty string in the same format as the `recipe_version` and `program_version` values written to the Factory_DB.
5. THE World_State SHALL contain, for each of EOL-A and EOL-B, a reference sample availability of AVAILABLE or UNAVAILABLE, a reason of 1 to 200 characters that is present if and only if the availability is UNAVAILABLE, and a Reference_Sample_Tolerance. The Reference_Sample_Tolerance SHALL be a positive number in `output_voltage` units that gives the largest absolute Reference_Sample_Check deviation that still counts as in tolerance.
6. THE World_State SHALL contain one actual recipe version and one actual program version for each of the three Station equipment units of ST-10, ST-20 and ST-30, as in effect at the shift end UTC_Timestamp, using the same fields as the approved configuration so that actual and approved values can be compared field by field.
7. FOR ALL valid World_State objects, serializing to JSON then parsing SHALL produce a World_State object equal to the original in every field, including exact floating-point values of True_Values and Tester_Bias parameters (round-trip property).
8. IF a World_State_File does not exist, is not valid JSON, lacks a required field, contains a value of the wrong type, contains an enum value outside the defined set, contains a timestamp that is not a UTC_Timestamp, or violates the reason rule of criterion 5, THEN THE Factory_Data_Package SHALL raise a validation error on load that names each offending field path, and SHALL return no World_State object.
9. WHEN the Tester_Bias of an EOL_Tester is evaluated at a UTC_Timestamp, THE Factory_Data_Package SHALL return the base offset if no onset is defined or the timestamp is earlier than the onset. Otherwise it SHALL return the base offset plus the slope multiplied by the hours elapsed since the onset. Repeated evaluations with the same inputs SHALL return the same value, including for timestamps outside the shift window.
10. IF a World_State lookup receives an SN that has no True_Value in the World_State, an EOL_Tester ID other than EOL-A or EOL-B, or a timestamp value that is not a UTC_Timestamp, THEN THE Factory_Data_Package SHALL raise a descriptive error that identifies the invalid input.
11. WHEN a Dataset is generated, THE Simulator SHALL write the World_State_File by serializing a World_State object, so that loading the file with the Factory_Data_Package raises no validation error and equal World_State objects produce byte-identical file content.

### Requirement 12: Ground Truth

**User Story:** As an evaluation author, I want a structured answer key per Dataset, so that investigation results can be scored automatically.

#### Acceptance Criteria

1. WHEN a Dataset is generated, THE Ground_Truth_Writer SHALL write exactly one Ground_Truth_File for that Dataset containing the Dataset_ID, the expected anomaly equipment, the Anomaly_Window, the expected Conclusion_Category, the set of Acceptable_Conclusions, the affected SN set, the key signals and the expected verification outcomes.
2. WHEN the Ground_Truth_Writer writes a Ground_Truth_File, THE Ground_Truth_Writer SHALL list exactly one expected verification outcome for each of the three checks, using only these values: cross-retest PASS or FAIL; reference sample check WITHIN_TOLERANCE, OUT_OF_TOLERANCE or UNAVAILABLE; configuration check MATCH or MISMATCH.
3. WHEN the Ground_Truth_Writer writes a Ground_Truth_File, THE Ground_Truth_Writer SHALL include in the affected SN set only SNs that exist in the `products` table of the Factory_DB of the same Dataset, with each SN listed at most once, and SHALL set the expected anomaly equipment, when present, to an equipment identifier that exists in the Factory_DB of the same Dataset.
4. WHEN the Ground_Truth_Writer writes a Ground_Truth_File, THE Ground_Truth_Writer SHALL include the expected Conclusion_Category in the set of Acceptable_Conclusions with a maximum Support_Level of HIGH, and SHALL list each Conclusion_Category at most once in that set.
5. FOR ALL valid Ground_Truth objects, serializing to JSON then parsing SHALL produce a Ground_Truth object equal in every field to the original (round-trip property).
6. WHEN the baseline Dataset `ds-00` is generated, THE Ground_Truth_Writer SHALL write an empty affected SN set, a null expected anomaly equipment and a null Anomaly_Window.
7. WHEN the Ground_Truth_Writer writes a Ground_Truth_File for Dataset `ds-01`, `ds-02` or `ds-03`, THE Ground_Truth_Writer SHALL write an Anomaly_Window with a start and an end in UTC_Timestamp format, with the start earlier than the end and both within the configured shift window.
8. WHEN the Ground_Truth_Writer writes a Ground_Truth_File for Dataset `ds-01`, `ds-02` or `ds-03`, THE Ground_Truth_Writer SHALL write at least one key signal, each as a non-empty text entry.
9. IF a Ground_Truth_File does not conform to the Ground_Truth model, THEN THE Simulator SHALL raise a descriptive validation error on load and SHALL return no Ground_Truth object.

### Requirement 13: Shared Enums

**User Story:** As a developer of downstream modules, I want shared enums, so that all modules use the same conclusion and support vocabulary.

#### Acceptance Criteria

1. THE Factory_Data_Package SHALL define the Conclusion_Category enum with exactly five members, TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE, where each member's serialized string value is identical to its uppercase member name.
2. THE Factory_Data_Package SHALL define the Support_Level enum with exactly three members, LOW, MEDIUM and HIGH, whose serialized string values are identical to their uppercase member names and which compare in the order LOW < MEDIUM < HIGH, so that a Support_Level can be checked against the maximum Support_Level of an Acceptable_Conclusion.
3. THE Factory_Data_Package SHALL define the EOL test result enum with exactly two members, whose serialized string values are PASS and FAIL.
4. THE Factory_Data_Package SHALL define the Origin enum with exactly two members, whose serialized string values are the lowercase strings `historical` and `verification`.
5. THE Factory_Data_Package SHALL define the equipment event type enum with exactly four members, whose serialized string values are the lowercase strings `state`, `alarm`, `maintenance` and `calibration`.
6. IF a string that does not exactly match (case-sensitive) a serialized value of the target enum is parsed into Conclusion_Category, Support_Level, EOL test result, Origin or equipment event type, including while a World_State or Ground_Truth model is being constructed or loaded, THEN THE Factory_Data_Package SHALL raise a validation error that names the enum and the rejected value, and SHALL NOT substitute a default member.

### Requirement 14: Scenario A – Tester Drift (ds-01)

**User Story:** As an evaluator, I want a tester drift scenario, so that the agent can be tested on identifying a measurement problem rather than a product problem.

#### Acceptance Criteria

1. WHEN scenario A is generated, THE Scenario_Modifier SHALL define the EOL-B Tester_Bias as zero for every UTC_Timestamp before the Drift_Onset (shift start plus 3 hours, 2026-11-02T09:00:00Z for the default shift), and as a positive slope multiplied by the elapsed time since the Drift_Onset for every UTC_Timestamp from the Drift_Onset to shift end inclusive. This gives a bias that is continuous at the Drift_Onset and strictly increasing after it.
2. WHEN scenario A is generated with the default configuration and the registry default seed of `ds-01`, THE Scenario_Modifier SHALL produce two EOL-B FAIL_Rates. The FAIL_Rate over first tests with ts from shift start up to but excluding the Drift_Onset SHALL be between 0.5% and 4.0% inclusive. The FAIL_Rate over first tests with ts from shift end minus 2 hours (2026-11-02T12:00:00Z for the default shift) up to shift end SHALL be between 12% and 25% inclusive.
3. WHEN scenario A is generated with the default configuration and the registry default seed of `ds-01`, THE Scenario_Modifier SHALL keep the EOL-A Tester_Bias identical in generation parameters to the baseline and produce an EOL-A FAIL_Rate between 0.5% and 4.0% inclusive over all EOL-A first tests of the full shift.
4. WHEN scenario A is generated, THE Scenario_Modifier SHALL keep all of the following identical in generation parameters to the baseline: the ST-20 program version, the ST-20 tightening angle distribution, the model mix and the EOL_Tester assignment rule. It SHALL also write zero rows to `process_changes`.
5. WHEN scenario A is generated, THE Scenario_Modifier SHALL record exactly 8 historical hourly EOL-B Reference_Sample_Checks, each with deviation equal to the EOL-B Tester_Bias at the check ts plus measurement noise. An ordinary least-squares regression of deviation against hours since shift start over all 8 checks SHALL yield a positive slope with a two-sided slope p-value below 0.01.
6. WHEN scenario A is generated, THE Scenario_Modifier SHALL create between 2 and 10 inclusive historical retests on EOL-A, with at most one retest per SN. Each retest SHALL have is_retest true, Origin historical and result PASS. Each SHALL reference via retest_of the first EOL-B test of the same SN, and that SN SHALL be in the affected SN set.
7. WHEN scenario A is generated, THE Simulator SHALL write a World_State in which, for every SN in the affected SN set, True_Value plus the EOL-A Tester_Bias at shift end lies within the lower and upper `output_voltage` limits (inclusive) of that SN's product model.
8. WHEN scenario A is generated, THE Simulator SHALL write a World_State in which the EOL-B reference sample is AVAILABLE, the absolute EOL-B Tester_Bias at shift end is greater than the EOL-B Reference_Sample_Tolerance, and the absolute EOL-A Tester_Bias at shift end is less than or equal to the EOL-A Reference_Sample_Tolerance.
9. WHEN scenario A is generated, THE Ground_Truth_Writer SHALL record all of the following:
   - EOL-B as the expected anomaly equipment.
   - An Anomaly_Window from the Drift_Onset to shift end.
   - TESTER_MEASUREMENT_DRIFT as the expected Conclusion_Category.
   - An Acceptable_Conclusion of TESTER_MEASUREMENT_DRIFT with maximum Support_Level HIGH.
   - Expected verification outcomes of cross-retest PASS, reference sample OUT_OF_TOLERANCE and configuration MATCH.
10. WHEN scenario A is generated, THE Ground_Truth_Writer SHALL define the affected SN set as exactly those SNs that meet three conditions: the first historical EOL test is on EOL-B, it has result FAIL and a ts at or after the Drift_Onset, and the SN's True_Value lies within the lower and upper `output_voltage` limits (inclusive) of its product model.
11. WHEN scenario A is generated, THE Scenario_Modifier SHALL apply the following tolerance pattern to historical Reference_Sample_Checks:
    - Every EOL-B check with ts before the Drift_Onset has an absolute deviation less than or equal to the EOL-B Reference_Sample_Tolerance.
    - The final EOL-B check of the shift has an absolute deviation greater than that tolerance and a result indicating out of tolerance.
    - Every EOL-A check has an absolute deviation less than or equal to the EOL-A Reference_Sample_Tolerance.
12. WHEN scenario A is generated, THE Simulator SHALL write a World_State in which the ST-20 actual recipe version and actual program version at shift end equal the ST-20 approved recipe version and approved program version.
13. WHEN scenario A is generated with the default configuration and the registry default seed of `ds-01`, THE Scenario_Modifier SHALL produce first-test FAIL_Rates that meet two conditions, comparing the final 3 hours of the shift (2026-11-02T11:00:00Z inclusive to shift end) with the first 2 hours of the shift (2026-11-02T06:00:00Z inclusive to 2026-11-02T08:00:00Z exclusive):
    - The EOL-B FAIL_Rate in the final 3 hours is at least 3.0 times the EOL-B FAIL_Rate in the first 2 hours, and the two-sided Fisher exact test p-value between those two rates is below 0.01.
    - The EOL-A FAIL_Rate in the final 3 hours does not meet both of the following together: being at least 2.0 times the larger of the EOL-A FAIL_Rate in the first 2 hours and 0.5%, and having a two-sided Fisher exact test p-value below 0.01 against the EOL-A FAIL_Rate in the first 2 hours.

### Requirement 15: Scenario B – Manufacturing Process Defect (ds-02)

**User Story:** As an evaluator, I want a process deviation scenario, so that the agent can be tested on tracing failures back to an upstream program change.

#### Acceptance Criteria

1. WHEN scenario B is generated, THE Scenario_Modifier SHALL change the ST-20 program version from P-2.3 to P-2.4 at 4 hours 8 minutes after shift start (2026-11-02T10:08:00Z with the default shift window), and SHALL record exactly one row in `process_changes` for the Dataset. That row SHALL have the ST-20 equipment_id, ts equal to the change time, a change_type indicating a program version change, old_value P-2.3, new_value P-2.4 and a non-null changed_by.
2. WHEN scenario B is generated, THE Scenario_Modifier SHALL generate ST-20 tightening angles for steps that use P-2.3 with the same generation parameters as the baseline, and SHALL shift the mean tightening angle for steps that use P-2.4. The shift SHALL be large enough that a two-sample Kolmogorov–Smirnov test between the `angle` process measurement values recorded with P-2.3 and those recorded with P-2.4 yields a p-value below 0.01.
3. WHEN scenario B is generated with the default configuration, THE Scenario_Modifier SHALL produce, for SNs whose ST-20 process step used program version P-2.4, at least 100 first (non-retest) historical EOL tests on each EOL_Tester and a FAIL_Rate of at least 12% on each EOL_Tester. In addition, for each EOL_Tester, the first-test FAIL_Rate over all SNs within the final 3 hours of the shift (2026-11-02T11:00:00Z inclusive to shift end) SHALL be at least 2.5 times that EOL_Tester's first-test FAIL_Rate in the first 2 hours of the shift (2026-11-02T06:00:00Z inclusive to 2026-11-02T08:00:00Z exclusive), with a two-sided Fisher exact test p-value between those two rates below 0.01, so that an anomaly detector that compares the last 3 hours with the first 2 hours flags both EOL_Testers.
4. WHEN scenario B is generated, THE Scenario_Modifier SHALL generate the Tester_Bias of both EOL_Testers and the assignment of SNs to EOL_Testers with the same generation parameters as the baseline Dataset `ds-00`.
5. WHEN scenario B is generated, THE Simulator SHALL schedule ST-20 process steps so that no step has a start_ts earlier than the program change time and an end_ts later than it. Every ST-20 process measurement in a step that starts at or after the change time SHALL record program_version P-2.4. Every ST-20 process measurement in a step that ends at or before the change time SHALL record program_version P-2.3.
6. WHEN scenario B is generated, THE Ground_Truth_Writer SHALL define the affected SN set as exactly the SNs whose ST-20 process measurements record program_version P-2.4, and SHALL exclude every SN whose ST-20 process measurements record P-2.3.
7. WHEN scenario B is generated, THE Simulator SHALL write a World_State in which all of the following hold:
   - The True_Value lies outside the `output_voltage` limits of the product model for every affected SN with a historical FAIL test.
   - The reference sample of each EOL_Tester is AVAILABLE.
   - The absolute Tester_Bias of each EOL_Tester is at most its Reference_Sample_Tolerance at every UTC_Timestamp within the shift window.
   - The ST-20 approved program version is P-2.3 and the ST-20 actual program version at the end of the shift is P-2.4.
8. WHEN scenario B is generated, THE Ground_Truth_Writer SHALL record:
   - ST-20 equipment as the anomaly equipment.
   - PROCESS_PARAMETER_DEVIATION as the expected Conclusion_Category.
   - An Anomaly_Window that starts at the program change time and ends at shift end (2026-11-02T10:08:00Z to 2026-11-02T14:00:00Z with the default shift window).
   - Key signals that include the ST-20 program change from P-2.3 to P-2.4 and the ST-20 tightening angle shift.
9. WHEN scenario B is generated, THE Ground_Truth_Writer SHALL record the expected verification outcomes as cross-retest FAIL, reference sample WITHIN_TOLERANCE and configuration MISMATCH.
10. WHEN scenario B is generated with the default configuration, THE Scenario_Modifier SHALL produce a FAIL_Rate between 0.5% and 4.0% on each EOL_Tester for SNs whose ST-20 process step used program version P-2.3.
11. WHEN scenario B is generated, THE Ground_Truth_Writer SHALL write a set of Acceptable_Conclusions that contains PROCESS_PARAMETER_DEVIATION with maximum Support_Level HIGH and contains no TESTER_MEASUREMENT_DRIFT entry.

### Requirement 16: Scenario C – Insufficient Evidence (ds-03)

**User Story:** As an evaluator, I want a scenario with a misleading surface signal and missing evidence, so that the agent can be tested on refusing an overconfident verdict.

#### Acceptance Criteria

1. WHEN scenario C is generated, THE Scenario_Modifier SHALL route to EOL-B between 80% and 90% (default 85%) of the Model B SNs and between 25% and 45% (default 35%) of the Model A SNs whose first historical EOL test ts lies within the Anomaly_Window. For SNs whose first historical EOL test ts lies before the Anomaly_Window start, it SHALL route between 40% and 60% (default 50%) of each product model to EOL-B.
2. WHEN scenario C is generated, THE Scenario_Modifier SHALL set the Model B Inherent_Defect_Probability to a configurable value between 10% and 30% with a default of 20%. It SHALL set the Model A Inherent_Defect_Probability to a configurable value between 0.5% and 3.0% with a default of 1.5%. Both probabilities SHALL apply unchanged over the full shift, where the Inherent_Defect_Probability is the probability that the True_Value of an SN lies outside the `output_voltage` limits of its product model.
3. WHEN scenario C is generated with the default configuration and the Scenario_Registry default seed, THE Scenario_Modifier SHALL produce an EOL-B FAIL_Rate that meets three conditions in each of two evaluation windows, the Anomaly_Window and the final 3 hours of the shift (2026-11-02T11:00:00Z inclusive to 2026-11-02T14:00:00Z): the EOL-B FAIL_Rate in the evaluation window is at least 2.0 times the EOL-B FAIL_Rate in the first 2 hours of the shift (2026-11-02T06:00:00Z inclusive to 2026-11-02T08:00:00Z exclusive); the two-sided Fisher exact test p-value between those two rates is below 0.01; and the EOL-B FAIL_Rate in the evaluation window is at least 1.5 times the EOL-A FAIL_Rate in the same evaluation window.
4. WHEN scenario C is generated with the default configuration and the Scenario_Registry default seed, THE Scenario_Modifier SHALL produce, for Model A and for Model B separately, an EOL-A versus EOL-B FAIL_Rate difference whose two-sided Fisher exact test p-value is above 0.05 in each of three windows: within the Anomaly_Window, within the final 3 hours of the shift (2026-11-02T11:00:00Z inclusive to 2026-11-02T14:00:00Z), and over the full shift.
5. WHEN scenario C is generated, THE Scenario_Modifier SHALL produce no Reference_Sample_Check on either EOL_Tester and no `eol_tests` row with is_retest true with a ts within the Anomaly_Window. It SHALL record the hourly Reference_Sample_Checks of both EOL_Testers before the Anomaly_Window start with an absolute deviation less than or equal to the Reference_Sample_Tolerance of the EOL_Tester.
6. WHEN scenario C is generated, THE Simulator SHALL write a World_State that meets five conditions: the EOL-B reference sample is UNAVAILABLE with the reason "out for calibration"; the EOL-A reference sample is AVAILABLE; the Tester_Bias of both EOL_Testers keeps the baseline generation parameters; the True_Value lies outside the `output_voltage` limits for every SN with a historical FAIL test; and all Station actual configurations equal the approved configurations.
7. WHEN scenario C is generated, THE Ground_Truth_Writer SHALL record INSUFFICIENT_EVIDENCE as the expected Conclusion_Category and no expected anomaly equipment. It SHALL record an Anomaly_Window from 2026-11-02T09:00:00Z (shift start plus 3 hours, inclusive) to 2026-11-02T14:00:00Z (shift end, inclusive), and expected verification outcomes of reference sample check on EOL-B UNAVAILABLE, cross-retest FAIL and configuration MATCH.
8. WHEN scenario C is generated, THE Ground_Truth_Writer SHALL write exactly four Acceptable_Conclusions, with no MATERIAL_LOT_ISSUE entry: INSUFFICIENT_EVIDENCE with maximum Support_Level HIGH, PRODUCT_MIX_SHIFT with maximum Support_Level MEDIUM, TESTER_MEASUREMENT_DRIFT with maximum Support_Level LOW, and PROCESS_PARAMETER_DEVIATION with maximum Support_Level LOW.
9. WHEN scenario C is generated, THE Scenario_Modifier SHALL assign Model B to between 5% and 15% (default 10%) of the SNs whose first historical EOL test ts lies before the Anomaly_Window and to between 40% and 50% (default 45%) of the SNs whose first historical EOL test ts lies within the Anomaly_Window. The full-shift Model A share SHALL stay between 65% and 75%, with a default-configuration value between 66% and 70%.
10. WHEN scenario C is generated, THE Simulator SHALL write a Factory_DB with zero `process_changes` rows and zero `equipment_events` rows with a ts within the Anomaly_Window, so that the routing and model mix changes are observable only through the model_id, tester_id and ts values of `products` and `eol_tests`.
11. WHEN scenario C is generated, THE Ground_Truth_Writer SHALL define the affected SN set as the Model B SNs whose first historical EOL test ran on EOL-B with a ts within the Anomaly_Window and result FAIL. It SHALL record three key signals: the EOL-B FAIL_Rate increase in the Anomaly_Window, the Model B share increase in the Anomaly_Window, and the absence of Reference_Sample_Checks in the Anomaly_Window.

### Requirement 17: Command-Line Interface

**User Story:** As a developer, I want a CLI and a make target, so that I can generate datasets with one command.

#### Acceptance Criteria

1. WHEN a user runs `python -m simulator generate --scenario <scenario> --seed <N> --out <dir>` with scenario baseline, a, b or c and an integer seed N in the range 0 to 4,294,967,295 inclusive, THE CLI SHALL generate the corresponding Dataset under `<dir>/<dataset_id>/`, containing exactly the Factory_DB, the World_State_File and the Ground_Truth_File, and exit with status code 0.
2. THE CLI SHALL map scenario baseline to `ds-00`, a to `ds-01`, b to `ds-02` and c to `ds-03`, and SHALL accept only these four lowercase scenario values.
3. WHEN generation completes successfully, THE CLI SHALL print a Signal_Summary to standard output containing the Dataset_ID, the product count (number of rows in `products`), the FAIL_Rate per EOL_Tester, the FAIL_Rate per EOL_Tester per product model, the minimum and maximum Reference_Sample_Check deviation per EOL_Tester (or an indication that the EOL_Tester has no Reference_Sample_Check rows), and the count of rows in `process_changes`. The CLI SHALL compute every value from rows with Origin historical and express each FAIL_Rate as a percentage rounded to two decimal places.
4. IF the CLI receives an unknown scenario, a missing `--scenario` or `--out` argument, a non-integer seed, a seed outside 0 to 4,294,967,295, or an output directory that cannot be created or written, THEN THE CLI SHALL print an error message to standard error naming the invalid argument, exit with a non-zero status code, write no Dataset artifacts, and leave any existing Dataset directory at `<dir>/<dataset_id>/` unchanged.
5. WHEN a user runs `make seed`, THE Simulator SHALL generate all four Datasets (`ds-00`, `ds-01`, `ds-02`, `ds-03`) under `data/` using the default seed of each Dataset from the Scenario_Registry, so that repeated `make seed` runs produce an identical Content_Hash for each Dataset. If generation of any Dataset fails, `make seed` SHALL exit with a non-zero status code.
6. WHEN the target Dataset directory already exists and generation succeeds, THE CLI SHALL replace the directory contents so that `<dir>/<dataset_id>/` contains exactly the three newly generated artifacts, with no files left from the previous run and no rows with Origin verification in the Factory_DB.
7. WHEN a user runs `python -m simulator generate` without the `--seed` argument, THE CLI SHALL use the Scenario_Registry default seed for the selected Dataset_ID and produce a Dataset whose Content_Hash equals that of a run with the default seed passed explicitly.
8. THE CLI SHALL compute the Signal_Summary from Factory_DB data only, and SHALL exclude from it the Scenario_Registry user-facing label, every Ground_Truth field name and value, and all World_State contents.
9. IF generation fails after it has started (for example, a generator exception or a write error), THEN THE CLI SHALL leave no partially written Dataset at `<dir>/<dataset_id>/`, keep any previously existing Dataset there byte-identical to its state before the run, print an error message to standard error describing the failure, and exit with a non-zero status code.

### Requirement 18: Scenario Registry

**User Story:** As a developer of the later API and UI, I want a scenario registry, so that the UI can present scenarios without exposing scenario identity in observable data.

#### Acceptance Criteria

1. THE Scenario_Registry SHALL list exactly four entries in the fixed order `ds-00`, `ds-01`, `ds-02`, `ds-03`. Each entry SHALL contain a Dataset_ID, a Scenario_Key, a user-facing label, a user-facing description and a default seed. Every call to list the entries SHALL return the same entries with the same content in the same order.
2. THE Scenario_Registry SHALL assign Scenario_Key `baseline` with label "Baseline – Normal Operation" to `ds-00`, Scenario_Key `a` with label "Scenario A – EOL Tester Drift" to `ds-01`, Scenario_Key `b` with label "Scenario B – Manufacturing Process Defect" to `ds-02`, and Scenario_Key `c` with label "Scenario C – Insufficient Evidence" to `ds-03`. This mapping SHALL be identical to the scenario-to-Dataset_ID mapping used by the CLI.
3. THE Scenario_Registry SHALL give each entry a non-empty label of at most 60 characters, a non-empty description of at most 200 characters, and a default seed that is a non-negative integer. The default seed SHALL equal the seed that `make seed` and the Reset_Function use for that Dataset_ID.
4. WHEN the Scenario_Registry lookup receives one of the Dataset_IDs `ds-00`, `ds-01`, `ds-02` or `ds-03`, THE Scenario_Registry SHALL return the single entry whose Dataset_ID exactly matches the given value. The returned entry SHALL equal the corresponding entry in the listing.
5. IF the Scenario_Registry lookup receives a Dataset_ID that does not exactly match one of `ds-00`, `ds-01`, `ds-02` or `ds-03`, THEN THE Scenario_Registry SHALL raise an error that names the rejected value and lists the four valid Dataset_IDs, and the registry entries SHALL remain unchanged. Matching is case-sensitive, does not trim whitespace, and treats an empty string as unknown.
6. WHEN the Scenario_Registry lookup receives one of the Scenario_Keys `baseline`, `a`, `b` or `c`, THE Scenario_Registry SHALL return the single entry with that Scenario_Key.
7. IF the Scenario_Registry lookup receives a Scenario_Key that does not exactly match one of `baseline`, `a`, `b` or `c`, THEN THE Scenario_Registry SHALL raise an error that names the rejected value and lists the four valid Scenario_Keys. Matching is case-sensitive.
8. THE Scenario_Registry SHALL be importable without importing the Ground_Truth_Writer. Importing it SHALL NOT read, create or modify any file under `data/`.
9. THE Scenario_Registry SHALL keep every Ground_Truth content out of each registry entry, including the affected SN set, the Anomaly_Window timestamps, the expected anomaly equipment, the Acceptable_Conclusion set and the expected verification outcomes.
10. THE Simulator SHALL NOT write any Scenario_Registry label or description, or the Scenario_Key `baseline`, into any table name, column name or text value of any Factory_DB. The single-letter Scenario_Keys `a`, `b` and `c` are excluded from this check, consistent with Requirement 10 criterion 3.

### Requirement 19: Dataset Reset

**User Story:** As a developer of the later API, I want to reset a dataset, so that each investigation session starts from the original generated state.

#### Acceptance Criteria

1. WHEN the Reset_Function is called with a Dataset_ID listed in the Scenario_Registry, THE Reset_Function SHALL regenerate the Factory_DB and World_State_File in `data/<dataset_id>/` from the scenario and default seed of that Dataset_ID's registry entry and the default Factory_Config. If the Dataset directory does not exist, THE Reset_Function SHALL create it, and it SHALL NOT create a Ground_Truth_File.
2. WHEN the Reset_Function completes, THE Reset_Function SHALL leave a Factory_DB that has zero `eol_tests` rows with Origin verification, zero `reference_sample_checks` rows with Origin verification, and zero `eol_measurements` rows that reference a verification-origin `eol_tests` row. The Dataset directory SHALL contain no SQLite write-ahead log, shared-memory or rollback journal file for the Factory_DB that existed before the call.
3. WHEN the Reset_Function completes for a Dataset, THE Simulator SHALL produce a Factory_DB and a World_State_File equal to those from a fresh generation with the same scenario, seed and Factory_Config. Equal means every Factory_DB table has identical rows when ordered by primary key, and the World_State_File is byte-identical. The first verification-origin identifier that ID_Formats generates for the reset Dataset SHALL equal the first verification-origin identifier it generates for the freshly generated Dataset.
4. IF the Reset_Function is called with a Dataset_ID not listed in the Scenario_Registry, THEN THE Reset_Function SHALL raise an error that names the rejected Dataset_ID. It SHALL create, modify or delete no file or directory under `data/`.
5. THE Reset_Function SHALL be importable and executable without importing the Ground_Truth_Writer. After one Reset_Function call in a fresh Python process, the Ground_Truth submodule SHALL NOT be among the modules loaded in that process.
6. WHEN the Reset_Function completes for a Dataset whose Ground_Truth_File existed before the call, THE Reset_Function SHALL leave that Ground_Truth_File byte-identical to its content before the call.
7. WHILE the Reset_Function is replacing the Factory_DB and World_State_File, THE Reset_Function SHALL write each replacement artifact to a temporary file in the Dataset directory and then rename it over the target. Any process that opens or holds open the Factory_DB or World_State_File during the reset, including the MCP server with an open SQLite connection, SHALL see either the complete pre-reset content or the complete regenerated content, and never an empty or partially written file.
8. IF regeneration or file replacement fails during a Reset_Function call, THEN THE Reset_Function SHALL raise an error indicating that the reset failed, leave the Factory_DB and World_State_File with their pre-call content, and remove every temporary file it created in the Dataset directory.

### Requirement 20: Verification-Origin Record Support

**User Story:** As a developer of the later verification engine, I want to append verification results to the Factory_DB, so that new evidence becomes observable to the investigator agent.

#### Acceptance Criteria

1. WHEN the verification engine calls the Append_Function with a batch of 1 to 5 EOL tests and zero or more reference sample checks, where each EOL test has an SN that exists in `products`, a tester_id of EOL-A or EOL-B, and one or more measurement entries, THE Factory_Data_Package SHALL insert, for each EOL test of the batch, one `eol_tests` row with Origin verification and one `eol_measurements` row per measurement entry, SHALL insert the rows of criterion 2 for each reference sample check of the batch, and SHALL commit all rows of that Append_Function call in a single transaction, so that either every row of the call is persisted or none is.
2. WHEN the verification engine calls the Append_Function with a batch that contains a reference sample check with a tester_id of EOL-A or EOL-B, THE Factory_Data_Package SHALL insert one `reference_sample_checks` row with Origin verification and with deviation equal to measured minus nominal for that check, within the same transaction as every other row of that Append_Function call.
3. THE Simulator SHALL set Origin to historical on every `eol_tests` and `reference_sample_checks` row it generates.
4. IF an Append_Function call supplies an sn, tester_id, retest_of or measurement test_id value that does not reference an existing row, THEN THE Factory_DB SHALL reject the insert with a foreign key error, and THE Factory_Data_Package SHALL roll back the transaction and persist none of the rows from that Append_Function call, including the rows of every other EOL test and reference sample check in the same batch.
5. WHEN the Append_Function inserts a verification-origin row, THE Factory_Data_Package SHALL assign its test_id, meas_id or check_id using the ID_Formats verification identifier function, SHALL store its ts as a UTC_Timestamp produced by Time_Util, and SHALL accept a ts that lies outside the configured shift window.
6. IF an Append_Function call supplies a tester_id that is not EOL-A or EOL-B, a model_id that differs from the model_id of the SN in `products`, is_retest true with a retest_of that is empty or references an `eol_tests` row of a different SN, is_retest false with a non-empty retest_of, zero measurement entries for an EOL test, more than 5 EOL tests or no record at all in one batch, or a ts that Time_Util cannot parse as a UTC_Timestamp, THEN THE Factory_Data_Package SHALL raise an error that names the invalid field and the batch position of the offending record, and SHALL persist none of the rows from that Append_Function call, including the rows of every valid record in the same batch.
7. WHEN an Append_Function call completes, either successfully or with an error, THE Factory_Data_Package SHALL leave every pre-existing row with Origin historical unchanged in the Factory_DB.
8. THE Factory_Data_Package SHALL expose, as a named constant, the failure_code value that the Simulator writes for an EOL test whose `output_voltage` measurement has result FAIL. THE Simulator SHALL use that constant when it sets the failure_code of such a test (Requirement 7 criterion 8), and THE Append_Function SHALL use the same constant as the failure_code of every verification-origin EOL test with result FAIL whose failing measurement has test_item `output_voltage`.

### Requirement 21: Package Layout for Isolation

**User Story:** As the system designer, I want a package layout that supports import contracts, so that the backend and MCP server cannot access the answer key through code.

#### Acceptance Criteria

1. THE Simulator SHALL place the Ground_Truth_Writer and all Ground_Truth models in the dedicated submodule `simulator.ground_truth`, and the CLI orchestration module that writes the Factory_DB, World_State_File and Ground_Truth_File SHALL be the only Simulator or Factory_Data_Package module that imports `simulator.ground_truth`.
2. THE Factory_Data_Package SHALL contain no Ground_Truth models, no code that reads or parses a Ground_Truth_File, and no reference to the `ground_truth.json` file name.
3. THE project SHALL define an import-linter forbidden contract that forbids the packages `backend` and `industrial_mcp` from importing `simulator.ground_truth` either directly or indirectly through any chain of intermediate modules, and running `lint-imports` from the repository root SHALL exit with status 0. The `tests/` directory is outside the contract and may import `simulator.ground_truth`.
4. THE project SHALL be a single uv project with one pyproject.toml at the repository root that declares `factory_data`, `simulator`, `industrial_mcp` and `backend` as top-level packages and requires Python 3.11 or later, and `uv sync` SHALL complete with exit status 0 on Python 3.11.
5. THE project SHALL define an import-linter contract that forbids the Factory_Data_Package from importing any module of the Simulator, `backend` or `industrial_mcp`, so that dependencies run only one way, from Simulator to Factory_Data_Package.
6. WHILE the `backend` and `industrial_mcp` packages have no functional code, THE project SHALL contain each of them as an importable placeholder package, so that `lint-imports` evaluates the contract in criterion 3 instead of failing because a contract module is missing.
7. THE Simulator SHALL implement the Scenario_Registry and the Reset_Function in modules that do not import `simulator.ground_truth` or the CLI orchestration module, directly or indirectly, so that `backend` and `industrial_mcp` can import them without violating the contract in criterion 3.

### Requirement 22: Deterministic Test Suite

**User Story:** As a developer, I want automated deterministic tests, so that data correctness and scenario signals are verified without an LLM.

#### Acceptance Criteria

1. THE Simulator test suite SHALL verify, for each of the Dataset_IDs `ds-00`, `ds-01`, `ds-02` and `ds-03`, that two independent generations with the registry default seed and the default Factory_Config, written to two separate temporary directories, produce identical Content_Hash values, and that a generation with a different seed produces a different Content_Hash value.
2. THE Simulator test suite SHALL verify, for each of the four Datasets generated with the registry default seed, that every foreign key value references an existing row, that every SN has exactly one process step at each of ST-10, ST-20 and ST-30 in Route order followed by exactly one first historical EOL test, and that every timestamp ordering and shift-window rule defined in Requirement 6 holds for every row.
3. THE Simulator test suite SHALL verify the statistical signal of each anomaly scenario on its registry default seed, with the same thresholds as Requirements 14 to 16:
   - In `ds-01`, the ordinary least-squares regression of EOL-B Reference_Sample_Check deviation against hours since shift start has a positive slope with a two-sided slope p-value below 0.01 (Requirement 14 criterion 5).
   - In `ds-01`, the EOL-B FAIL_Rate in the final 3 hours of the shift is at least 3.0 times the EOL-B FAIL_Rate in the first 2 hours with a two-sided Fisher exact test p-value below 0.01, and the EOL-A FAIL_Rate in the final 3 hours does not meet both "at least 2.0 times the larger of the EOL-A first-2-hours FAIL_Rate and 0.5%" and "two-sided Fisher exact test p-value below 0.01" (Requirement 14 criterion 13).
   - In `ds-02`, the two-sample Kolmogorov–Smirnov test between ST-20 angle values recorded with program_version P-2.3 (before 2026-11-02T10:08:00Z) and those recorded with P-2.4 (at or after 2026-11-02T10:08:00Z) has a p-value below 0.01 (Requirement 15 criterion 2).
   - In `ds-02`, for SNs whose ST-20 process step used P-2.4, each EOL_Tester has at least 100 first historical EOL tests and a FAIL_Rate of at least 12%, and each EOL_Tester's FAIL_Rate in the final 3 hours of the shift is at least 2.5 times its FAIL_Rate in the first 2 hours with a two-sided Fisher exact test p-value below 0.01 (Requirement 15 criterion 3).
   - In `ds-03`, both within the Anomaly_Window and within the final 3 hours of the shift, the EOL-B FAIL_Rate is at least 2.0 times the EOL-B FAIL_Rate in the first 2 hours of the shift, the two-sided Fisher exact test p-value between those two rates is below 0.01, and the EOL-B FAIL_Rate is at least 1.5 times the EOL-A FAIL_Rate in the same window (Requirement 16 criterion 3).
   - In `ds-03`, for Model A and for Model B separately, the two-sided Fisher exact test of the EOL-A versus EOL-B FAIL_Rate difference has a p-value above 0.05 within the Anomaly_Window, within the final 3 hours of the shift and over the full shift (Requirement 16 criterion 4).
4. THE Simulator test suite SHALL verify, for each of the four Datasets, that no table name, column name or text value in the Factory_DB meets any condition listed in Requirement 10 criterion 3 (which covers Ground_Truth field names, scenario names, Scenario_Registry labels and Conclusion_Category values), and SHALL report the matched value together with its table and column when this check fails.
5. THE Simulator test suite SHALL pass when executed with network access disabled, without any LLM API credential configured and without calling an LLM.
6. THE Simulator test suite SHALL contain no test carrying the pytest `llm` marker, so that `pytest -m "not llm"` selects and runs every Simulator test.
7. WHEN `pytest -m "not llm"` runs the full Simulator test suite on a developer laptop, THE Simulator test suite SHALL complete within 60 seconds of wall-clock time as reported by pytest, generating each Dataset used by checks other than the reproducibility check in criterion 1 at most once per test session.
8. THE Simulator test suite SHALL include Hypothesis property-based tests verifying that formatting and then parsing any UTC_Timestamp through the Time_Util, serializing and then loading any World_State, and serializing and then loading any Ground_Truth each return a value equal to the original, and that every identifier generated by the ID_Formats passes the ID_Formats validation for its entity type.
