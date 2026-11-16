# Requirements Document

## Introduction

Factory CSI is an AI manufacturing quality investigation copilot built for Kiroween 2026 in the Frankenstein category. It combines simulated industrial systems (MES, PPM, EOL), an MCP server, statistical quality analytics, an LLM agent and human-in-the-loop verification. This spec covers everything that turns the modules of the other specs into a buildable, testable, demonstrable and submittable project: the repository foundation, the Kiro configuration (steering, hooks, dev-time MCP), containerization, the evaluation harness, the documentation and the pre-submission checks.

The repository foundation (Requirements 1 to 5) is implemented first, before any code of the other specs, so that every later phase starts with working `make setup`, `make lint` and `make test-fast` targets, active hooks and committed steering.

In scope:
- Root Python project configuration (uv, ruff, pytest, import-linter), the frontend scaffold, the Makefile, `.gitignore`, `.dockerignore`, `.env.example` and the LICENSE.
- Kiro Steering_Files, Hook_Files with their Hook_Scripts, and the Dev_MCP_Config.
- The Backend_Image, the Frontend_Image and the Compose_Stack for a local demo.
- The Evaluation_Harness (`make eval`) with its metrics and outputs.
- README.md, docs/architecture.md, docs/demo-script.md, docs/dev-log.md, docs/evaluation.md, docs/submission.md and KIRO_USAGE.md.
- The Submission_Checker, the Clean_Clone_Script and an optional CI_Workflow.

Out of scope:
- Public cloud deployment. It is deferred; the Compose_Stack stays deployable later. A later deployment will need: a host, HTTPS termination, protection of the LLM API key, request rate limiting, an LLM cost cap, authentication or an access gate, and a public bind address for the Frontend_Image.
- Recording and uploading the demo video and submitting the Devpost form. The user does these manually.
- A WebGL or 3D factory view.
- The functional behavior of the simulator, MCP server, investigation engine, verification loop, API and UI, which belongs to their own specs.

Assumptions:
- The LICENSE copyright holder is "Liu Gan" and the copyright year is 2026.
- Raw evaluation results (`evaluation/results/<timestamp>.json`) are git-ignored. Only `evaluation/results/latest-summary.json` and `docs/evaluation.md` are committed, so the repository shows the latest evaluation without accumulating raw run data.
- The Frontend_Image is published on `127.0.0.1:18473` and the Backend_Image on `127.0.0.1:18474`, because the MVP has no authentication and calls a paid LLM. Binding to a public interface is part of the deferred deployment.
- The JSON that Kiro passes on STDIN to a PostFileSave command hook contains the saved file path. The exact field name is confirmed against the Kiro hook documentation during implementation. Every Hook_Script also accepts the path as its first command-line argument, for manual runs and tests.
- Kiro may not surface the output of a PostFileSave command hook. Each Hook_Script therefore writes its full output to `logs/hooks/<hook-name>.log` and prints a one-line summary (Requirement 7 criterion 10), so results stay visible if Kiro does not show them.
- The per-Case investigation budgets are 40 LLM calls (not 25) and 20 MCP tool calls, as enforced by the investigation-engine spec. The Evaluation_Harness and the documentation use these values.
- Example model strings in `.env.example` for providers other than DeepSeek are illustrative and are checked against the LiteLLM provider documentation at implementation time.
- The Node.js toolchain is Node 20 LTS or later with npm. The Python toolchain is uv with Python 3.11 or later.
- The Evaluation_Harness works on its own copy of the Datasets under `var/eval/` so that it never resets the Datasets a running development server uses.

Dependencies:
- virtual-factory-simulator: `python -m simulator generate`, `make seed`, the Scenario_Registry, the Reset_Function, the Ground_Truth_File and the import-linter contracts of its Requirement 21.
- industrial-mcp-server: `python -m industrial_mcp --dataset <id> --data-dir <dir>` over stdio.
- investigation-engine and verification-loop: the investigation graph, the LLM health check, the Evidence_Registry, the Auto_Approve_Policy, Judgment_Changes, the Report and the Banned_Wording_Checker.
- investigation-api: the application `backend.api.app:app`, its settings (DATA_DIR, APP_DB_PATH, CHECKPOINT_DB_PATH, LOG_DIR, CORS_ORIGINS, HOST, PORT), `GET /api/health`, `GET /api/llm/status`, the Case detail and the canonical Case event catalog (`evidence_added`, `citation_dropped`, `proposal_rejected_by_validator`, `verification_executed`, `judgment_changed`, `conclusion_finalized`, `report_generated`, `llm_call`) from which the Evaluation_Harness computes its metrics (Requirement 13 criterion 12).
- investigation-workspace-ui: the SPA built from `frontend/`.
- External tools: git, bash, uv, Node 20+ with npm, Docker Engine with Docker Compose v2.

## Glossary

- **Repository**: The public Git repository of Factory CSI, with `.kiro/` at its root.
- **Root_Project**: The single uv Python project defined by the root `pyproject.toml` and `uv.lock`, containing the packages `factory_data`, `simulator`, `industrial_mcp`, `backend` and `evaluation`.
- **Placeholder_Package**: An importable package or module that contains no functional code yet, created by the repository foundation so that tooling and import contracts work before the owning spec is implemented.
- **Import_Contracts**: The import-linter contracts declared in the root `pyproject.toml` and checked by `lint-imports`.
- **Frontend_App**: The React, TypeScript and Vite single-page application in `frontend/`.
- **Makefile**: The root `Makefile` that provides the developer and submission commands.
- **LLM_Test**: A pytest test that calls the real LLM provider and carries the pytest marker `llm`.
- **Deterministic_Test**: A pytest test without the marker `llm`. It calls no LLM and needs no network access.
- **Env_Template**: The committed file `.env.example` that documents every environment setting with safe placeholder values.
- **Secret_Value**: An LLM API key or any other credential, token or private key.
- **Steering_Files**: The Markdown files in `.kiro/steering/` that give Kiro's agent persistent project context.
- **Hook_Files**: The Kiro hook definitions in `.kiro/hooks/*.json`.
- **Hook_Scripts**: The bash scripts in `scripts/hooks/` that the Hook_Files run.
- **Test_Hook**: The hook `python-tests-on-save` and its script `scripts/hooks/run_related_tests.sh`.
- **Frontend_Hook**: The hook `frontend-typecheck-on-save` and its script `scripts/hooks/frontend_check.sh`.
- **Secret_Guard**: The hook `secret-guard` and its script `scripts/hooks/secret_guard.sh`.
- **Secret_Pattern**: A regular expression the Secret_Guard uses to detect a possible Secret_Value.
- **Masked_Value**: A detected value in which every character except the last 4 is replaced by `*`.
- **Allow_Marker**: The literal text `secret-guard: allow` placed on a source line to suppress a generic Secret_Pattern match on that line.
- **Dev_MCP_Config**: The file `.kiro/settings/mcp.json` that registers the Industrial_MCP_Server for Kiro's development agent as four servers, `industrial-mcp-ds-00` to `industrial-mcp-ds-03`, one per Dataset.
- **Industrial_MCP_Server**: The FastMCP stdio server started with `python -m industrial_mcp`.
- **Investigation_Engine**: The LangGraph investigation agent in `backend/`, including its LLM health check.
- **Verification_Loop**: The part of the investigation graph that proposes, validates, approves and executes verifications and updates hypotheses.
- **LLM_Health_Status**: The result of the Investigation_Engine LLM health check: OK, UNAVAILABLE or MISCONFIGURED.
- **Dataset**: A generated set of artifacts under `<data dir>/<dataset_id>/`: `factory.db`, `world_state.json` and `ground_truth.json`.
- **Dataset_ID**: One of `ds-00`, `ds-01`, `ds-02` or `ds-03`.
- **Factory_DB**: The SQLite file `factory.db` of a Dataset, containing observable system data only.
- **Ground_Truth**: The answer key of a Dataset, including the expected anomaly equipment, the Acceptable_Conclusion set and the expected verification outcomes.
- **Ground_Truth_File**: The file `ground_truth.json` of a Dataset, the serialized Ground_Truth.
- **Scenario_Registry**: The simulator component that lists the four Datasets with Dataset_ID, Scenario_Key, user-facing label, user-facing description and default seed.
- **Reset_Function**: The simulator function that restores the Factory_DB and world state of a Dataset to its generated state.
- **UTC_Timestamp**: A text value in the form `YYYY-MM-DDTHH:MM:SSZ`.
- **Conclusion_Category**: The shared enum of investigation conclusions: TESTER_MEASUREMENT_DRIFT, PROCESS_PARAMETER_DEVIATION, PRODUCT_MIX_SHIFT, MATERIAL_LOT_ISSUE and INSUFFICIENT_EVIDENCE.
- **Support_Level**: The shared ordered enum LOW < MEDIUM < HIGH.
- **Acceptable_Conclusion**: A Ground_Truth entry of a Conclusion_Category and a maximum Support_Level.
- **App_Settings**: The backend settings defined by the investigation-api spec Requirement 1.
- **App_DB**: The backend application store at APP_DB_PATH (default `./var/app.db`).
- **Case**: One investigation tracked by the backend, with its status, audit records, evidence and Report.
- **Evidence_Item**: One recorded piece of evidence of a Case, identified by an Evidence_ID.
- **Evidence_ID**: The identifier of an Evidence_Item in the form `EV-` followed by at least three digits.
- **Evidence_Registry**: The per-Case collection of Evidence_Items.
- **Verification_Proposal**: A verification suggested by the Verification_Loop, with a verification type (cross_retest, reference_sample_check or process_config_check), parameters and a rank.
- **Proposal_Validator**: The deterministic Verification_Loop component that accepts or rejects a Verification_Proposal.
- **Backend_Image**: The container image built from `backend/Dockerfile`.
- **Frontend_Image**: The container image built from `frontend/Dockerfile`.
- **Entrypoint**: The start script of the Backend_Image.
- **Compose_Stack**: The services, volumes and settings defined in the root `docker-compose.yml`.
- **Evaluation_Harness**: The top-level Python package `evaluation/`, run with `make eval` or `python -m evaluation`.
- **Evaluation_Run**: One investigation the Evaluation_Harness executes on one Dataset.
- **Auto_Approve_Policy**: The policy defined by the verification-loop spec: approve the rank-1 Verification_Proposal, and conclude when no valid Verification_Proposal is offered or the investigation limits are reached.
- **Run_Metrics**: The metrics the Evaluation_Harness computes for one Evaluation_Run (Requirement 13).
- **Results_File**: The file `evaluation/results/<YYYYMMDDTHHMMSSZ>.json` that holds all Run_Metrics of one harness invocation.
- **Latest_Summary**: The committed file `evaluation/results/latest-summary.json` with the aggregated results of the most recent completed harness invocation.
- **Evaluation_Report**: The committed file `docs/evaluation.md` generated by the Evaluation_Harness.
- **Limitations_Statement**: The sentence "3 synthetic scenarios, N runs each; not evidence of production-grade root-cause accuracy", with N replaced by the number of runs per scenario.
- **Judgment_Change**: The recorded change of one hypothesis in one verification round, including the Evidence_IDs that caused it.
- **Report**: The investigation report of a Case, in full form with 10 sections or in short form.
- **Banned_Wording_Checker**: The deterministic function of the verification-loop spec that finds banned overclaiming phrases in text.
- **README**: The root file `README.md`.
- **Architecture_Doc**: The file `docs/architecture.md`.
- **Demo_Script**: The file `docs/demo-script.md`.
- **Dev_Log**: The file `docs/dev-log.md`.
- **Kiro_Usage_Doc**: The root file `KIRO_USAGE.md`.
- **Submission_Draft**: The file `docs/submission.md`.
- **Submission_Checker**: The script `scripts/check_submission.sh`, run with `make check-submission`.
- **Clean_Clone_Script**: The script `scripts/clean_clone_check.sh`.
- **CI_Workflow**: The optional GitHub Actions workflow `.github/workflows/ci.yml`.

## Requirements

### Requirement 1: Root Python Project and Import Contracts

**User Story:** As a developer, I want one root Python project with lint, test and import-contract configuration, so that every module is built, linted and tested the same way from the first commit.

#### Acceptance Criteria

1. THE Root_Project SHALL be defined by a single root `pyproject.toml` that requires Python 3.11 or later and declares the top-level packages `factory_data`, `simulator`, `industrial_mcp`, `backend` and `evaluation`, and the Repository SHALL contain the matching `uv.lock` and a `.python-version` file with the value `3.11`.
2. WHEN a developer runs `uv sync` in a clean clone, THE Root_Project SHALL install the runtime dependencies and a development dependency group containing at least pytest, ruff and import-linter, and SHALL exit with status 0.
3. THE root `pyproject.toml` SHALL configure ruff with target version `py311` and at least the rule sets `E`, `F` and `I`, and SHALL exclude `frontend/`, `data/`, `var/` and `logs/` from linting.
4. THE root `pyproject.toml` SHALL configure pytest with `testpaths = ["tests"]`, SHALL register the marker `llm` with a description stating that the test calls a real LLM provider and costs money, and SHALL enable strict markers so that an unregistered marker fails collection.
5. THE root pytest configuration SHALL deselect LLM_Tests by default, so that a bare `pytest` invocation runs only Deterministic_Tests, and LLM_Tests SHALL run only when a marker expression that selects `llm` is passed explicitly.
6. THE Import_Contracts SHALL include the contracts of the virtual-factory-simulator spec Requirement 21 (`backend` and `industrial_mcp` must not import `simulator.ground_truth` directly or indirectly; `factory_data` must not import `simulator`, `backend` or `industrial_mcp`) and an additional forbidden contract that `factory_data`, `simulator`, `industrial_mcp` and `backend` must not import `evaluation`.
7. THE Import_Contracts SHALL leave `evaluation` and `tests` outside every forbidden contract, so that the Evaluation_Harness and tests may import `simulator.ground_truth`.
8. THE repository foundation SHALL create a Placeholder_Package for every package and module named in an Import_Contract that does not exist yet, including `backend`, `industrial_mcp`, `evaluation` and `simulator.ground_truth`, so that `lint-imports` evaluates the contracts and exits with status 0.
9. THE repository foundation SHALL include one Deterministic_Test at `tests/unit/test_smoke.py` that imports each top-level package, so that `pytest -m "not llm"` collects at least one test and exits with status 0 before other specs add tests.
10. THE Repository SHALL contain the test directories `tests/unit/`, `tests/integration/`, `tests/llm/` and `tests/eval/`, and every test file under `tests/llm/` SHALL carry the marker `llm` on every test it defines.

### Requirement 2: Frontend Scaffold

**User Story:** As a frontend developer, I want a configured React and TypeScript scaffold with lint, typecheck and tests, so that UI work starts on a working toolchain.

#### Acceptance Criteria

1. THE Frontend_App SHALL be a Vite, React and TypeScript project in `frontend/` with TypeScript `strict` mode enabled, Tailwind CSS configured, shadcn/ui initialized (a committed `components.json`), ESLint configured for TypeScript and React, and Vitest configured.
2. THE Repository SHALL contain `frontend/package-lock.json`, and `npm ci` in `frontend/` SHALL install the dependencies from it and exit with status 0.
3. THE `frontend/package.json` SHALL define the scripts `dev`, `build`, `preview`, `typecheck` (TypeScript check without emitting files), `lint` (ESLint over the project) and `test` (Vitest in single-run mode), and SHALL declare Node 20 or later in its `engines` field.
4. WHEN a developer runs `npm run dev` in `frontend/`, THE Frontend_App SHALL serve on `http://localhost:5173` and SHALL proxy every request whose path starts with `/api` to `http://127.0.0.1:18474` without buffering Server-Sent Events.
5. THE Frontend_App SHALL call the backend only through relative `/api` paths, so that the same build works behind the Vite proxy and behind the Frontend_Image proxy.
6. THE repository foundation SHALL include one Vitest smoke test in `frontend/`, so that `npm run test` finds at least one test and exits with status 0 before the UI spec adds tests.

### Requirement 3: Makefile Targets

**User Story:** As a developer or judge, I want short make targets for every common task, so that I can set up, test, evaluate and run the project without reading build internals.

#### Acceptance Criteria

1. THE Makefile SHALL define the targets `setup`, `seed`, `test`, `test-fast`, `lint`, `eval`, `dev-backend`, `dev-frontend`, `docker-up` and `check-submission`, each declared `.PHONY`, and a `help` target that lists every target with a one-line description.
2. WHEN a developer runs `make setup`, THE Makefile SHALL run `uv sync` and `npm ci` in `frontend/`. IF uv, node or npm is not found on PATH, THEN THE Makefile SHALL print a message that names the missing tool and the minimum version, and exit with a non-zero status before installing anything.
3. WHEN a developer runs `make seed`, THE Makefile SHALL generate the Datasets `ds-00` to `ds-03` under `data/` as defined in the virtual-factory-simulator spec Requirement 17 criterion 5.
4. WHEN a developer runs `make test-fast`, THE Makefile SHALL run `pytest -m "not llm"`, `lint-imports`, the Frontend_App `test` script and the Frontend_App `typecheck` script, SHALL run all four even when an earlier one fails, and SHALL exit with a non-zero status if any of them failed.
5. THE `make test-fast` target SHALL pass without an LLM API key, without network access to an LLM provider and without a `.env` file.
6. WHEN a developer runs `make test`, THE Makefile SHALL print a notice that LLM_Tests require a valid LLM configuration in `.env` and cost a small amount of money, then run everything `make test-fast` runs plus pytest with a marker expression that selects all tests including `llm`.
7. IF an LLM_Test runs while the LLM_Health_Status is not OK, THEN THE test suite SHALL fail that test with a message naming the LLM_Health_Status and the sanitized reason, and SHALL NOT skip it silently.
8. WHEN a developer runs `make lint`, THE Makefile SHALL run `ruff check .`, the Frontend_App `lint` script and the Frontend_App `typecheck` script, and exit with a non-zero status if any of them reports an error.
9. WHEN a developer runs `make eval`, THE Makefile SHALL run `uv run python -m evaluation` and SHALL pass the optional make variables `RUNS` and `DATASETS` to the `--runs` and `--datasets` options.
10. THE `dev-backend` target SHALL run `uv run uvicorn backend.api.app:app --reload --host 127.0.0.1 --port 18474`, and the `dev-frontend` target SHALL run the Frontend_App `dev` script. THE README SHALL document both as long-running commands that the developer starts in separate terminals.
11. WHEN a developer runs `make docker-up`, THE Makefile SHALL run `docker compose up --build`. IF `.env` does not exist, THEN THE Makefile SHALL print the instruction `cp .env.example .env` and exit with a non-zero status without starting containers.
12. WHEN a developer runs `make check-submission`, THE Makefile SHALL run the Submission_Checker and return its exit status.

### Requirement 4: Git Ignore Rules, Repository Hygiene and License

**User Story:** As the project owner, I want ignore rules and a license that keep secrets and generated data out of the public repository while keeping the Kiro artifacts in it, so that the submission is complete and safe.

#### Acceptance Criteria

1. THE root `.gitignore` SHALL ignore `.env`, the root directories `/data/`, `/var/` and `/logs/` (anchored to the Repository root, so that directories such as `factory_data/` and `frontend/src/data/` are not ignored), `node_modules/`, `dist/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.import_linter_cache/` and `frontend/coverage/`.
2. THE root `.gitignore` SHALL ignore every file in `evaluation/results/` except `evaluation/results/latest-summary.json` and `evaluation/results/.gitkeep`.
3. THE root `.gitignore` SHALL NOT ignore `.env.example`, and `git check-ignore` SHALL report none of `.kiro/`, `.kiro/specs/`, `.kiro/steering/`, `.kiro/hooks/` and `.kiro/settings/mcp.json`, or any file below them, as ignored.
4. THE Repository SHALL contain a root `.dockerignore` that excludes `.env`, `.git/`, `data/`, `var/`, `logs/`, `node_modules/`, `frontend/node_modules/`, `frontend/dist/`, `.venv/`, `tests/` and `evaluation/results/` from every Docker build context.
5. THE Repository SHALL contain a root `LICENSE` file with the unmodified MIT License text, the copyright line `Copyright (c) 2026 Liu Gan`, and no additional terms.
6. THE `README` License section and the `pyproject.toml` license field SHALL both state MIT.
7. THE Repository SHALL contain no Secret_Value in any git-tracked file, as verified by the Secret_Guard `--all` mode.

### Requirement 5: Environment Template and LLM Provider Configuration

**User Story:** As a user, I want a documented environment template, so that I can configure the LLM provider and app settings without reading source code.

#### Acceptance Criteria

1. THE Env_Template SHALL define the LLM settings `LLM_PROVIDER=deepseek`, `LLM_MODEL=deepseek/deepseek-flash`, `LLM_API_KEY=` with an empty value, `LLM_BASE_URL=` with an empty value and `LLM_THINKING=false`.
2. THE Env_Template SHALL define the app settings DATA_DIR, APP_DB_PATH, CHECKPOINT_DB_PATH, LOG_DIR, CORS_ORIGINS, HOST and PORT with values equal to the App_Settings defaults of the investigation-api spec Requirement 1 criterion 1.
3. THE Env_Template SHALL contain a comment above each setting that states its purpose and allowed values, and a comment block explaining that LLM_MODEL is a LiteLLM model string whose provider prefix selects the provider.
4. THE Env_Template SHALL contain one commented example configuration for each of DeepSeek, OpenAI, Gemini, Qwen via DashScope, OpenRouter and Ollama. Each example SHALL show LLM_PROVIDER, LLM_MODEL with the LiteLLM provider prefix, whether LLM_API_KEY is required, and LLM_BASE_URL when the provider needs it. The Ollama example SHALL show `http://localhost:11434` for local development and `http://host.docker.internal:11434` for the Compose_Stack.
5. THE Env_Template SHALL state in a comment that `.env` is git-ignored, that a real key belongs only in `.env`, and that without a valid key the app runs with investigation disabled and no fallback output.
6. THE Env_Template SHALL contain no Secret_Value. Every credential setting SHALL have an empty value or a placeholder enclosed in angle brackets, for example `<your-api-key>`.
7. WHEN a setting is added to App_Settings or to the LLM configuration by any spec, THE Env_Template SHALL be updated in the same implementation phase with the new setting and its comment.

### Requirement 6: Kiro Steering Files

**User Story:** As a developer working with Kiro's agent, I want steering files that record the project's actual decisions, so that generated code follows the architecture, data semantics, agent rules, testing rules and security boundaries.

#### Acceptance Criteria

1. THE Steering_Files SHALL include `product.md`, `tech.md`, `structure.md`, `testing.md` and `security-boundaries.md`, each with front-matter `inclusion: always`.
2. THE Steering_Files SHALL include `industrial-data-semantics.md` with front-matter `inclusion: fileMatch` and a `fileMatchPattern` that matches every file under `simulator/`, `industrial_mcp/` and `factory_data/` and no file outside them.
3. THE Steering_Files SHALL include `agent-principles.md` with front-matter `inclusion: fileMatch` and a `fileMatchPattern` that matches every file under `backend/agent/`, `backend/llm/` and `backend/evidence/` and no file outside them.
4. THE `product.md` file SHALL describe the product purpose, the target user (manufacturing quality engineer), the three innovations (cross-system manufacturing forensics, evidence-grounded investigation, next best verification), the four Scenario_Registry labels, the fictional-data and simulated-verification nature, and the Kiroween 2026 Frankenstein category.
5. THE `tech.md` file SHALL describe the stack (uv, Python 3.11+, FastAPI, LangGraph, LiteLLM with default model `deepseek/deepseek-flash`, FastMCP over stdio, SQLite, React, TypeScript, Vite, Tailwind, shadcn/ui), the rule that an unavailable LLM disables investigation with no fallback mode, and the Makefile targets of Requirement 3.
6. THE `structure.md` file SHALL describe the top-level directories, the one-way package dependencies enforced by the Import_Contracts, the test directory layout, and the seven spec directories under `.kiro/specs/`.
7. THE `industrial-data-semantics.md` file SHALL describe the meaning of the MES, PPM and EOL data, the identifier formats, the UTC_Timestamp form, the Origin values historical and verification, and the separation of observable data, world state and Ground_Truth.
8. THE `agent-principles.md` file SHALL state that every claim cites Evidence_IDs, that banned overclaiming phrases are not allowed, that every verification requires human approval, that investigation budgets are enforced by code, and that LLM failures surface as errors and never as invented fallback text.
9. THE `testing.md` file SHALL state the marker rules of Requirement 1 criteria 4 and 5, where each kind of test lives, that `make test-fast` passes before each commit, that Deterministic_Tests need no network, and how the Hook_Files and the Evaluation_Harness relate to the test suite.
10. THE `security-boundaries.md` file SHALL state that Secret_Values exist only in `.env`, that keys are never committed or logged, that `backend` and `industrial_mcp` never access Ground_Truth, that the system never controls real equipment, that the system produces no fallback text when the LLM is unavailable, and that all data and verification results are labelled as simulated.
11. WHEN an implementation phase changes a decision that a Steering_File records, THE Steering_File SHALL be updated in the same phase, and THE Steering_Files SHALL contain no statement that contradicts the requirements of the seven specs.

### Requirement 7: Save-Time Test and Typecheck Hooks

**User Story:** As a developer, I want related tests, lint and typechecks to run when I save a file, so that I see regressions immediately without running the full suite.

#### Acceptance Criteria

1. THE Hook_Files SHALL use the Kiro hook schema with `"version": "v1"` and PascalCase trigger names, and SHALL be created with Kiro's hook tooling.
2. THE Hook_Files SHALL define the Test_Hook with trigger PostFileSave, matcher `\.py$`, a command that runs `scripts/hooks/run_related_tests.sh`, and a timeout of at most 120 seconds.
3. WHEN the Test_Hook runs, THE Test_Hook SHALL read the hook event JSON from STDIN without requiring jq, extract the saved file path, and convert it to a path relative to the Repository root.
4. THE Test_Hook SHALL map the saved path to test targets as follows: `simulator/**` and `factory_data/**` map to `tests/unit/simulator/`; `industrial_mcp/**` maps to `tests/integration/mcp/`; `backend/**` maps to `tests/unit/backend/`; `evaluation/**` maps to `tests/eval/`; a file under `tests/` maps to that file itself.
5. WHEN the saved path has a mapping, THE Test_Hook SHALL run `ruff check <file>` and then `pytest -m "not llm" -q` on the mapped targets that exist, and SHALL exit with status 0 only if both commands succeed.
6. IF the saved path has no mapping, or none of its mapped targets exists yet, THEN THE Test_Hook SHALL still run `ruff check <file>`, print a message stating that no related tests were found for that path, and skip pytest.
7. IF ruff or pytest fails, THEN THE Test_Hook SHALL exit with a non-zero status so that Kiro surfaces the output. The hook SHALL NOT attempt to block or revert the save.
8. THE Hook_Files SHALL define the Frontend_Hook with trigger PostFileSave, matcher `frontend/.*\.(ts|tsx)$`, a command that runs `scripts/hooks/frontend_check.sh`, and a timeout of at most 120 seconds.
9. WHEN the Frontend_Hook runs, THE Frontend_Hook SHALL run the Frontend_App `typecheck` script and ESLint on the saved file, and SHALL exit with a non-zero status if either reports an error.
10. THE Test_Hook and the Frontend_Hook SHALL write their complete output of the latest run to `logs/hooks/<hook-name>.log`, overwriting the previous run, and SHALL print to standard output a single summary line that states the saved path, the overall result (passed or failed) and the log file path, because Kiro may not surface the output of a PostFileSave command hook.
11. IF the hook event JSON contains no file path and no path argument is given, THEN THE Hook_Script SHALL print a message stating that no file path was received and exit with a non-zero status.
12. THE Test_Hook SHALL provide a `--print-targets <path>` option that prints the mapped test targets for a path without running any command, for use by the tooling tests.
13. THE Hook_Scripts SHALL accept the saved file path as their first command-line argument and SHALL use it when it is given. The name of the STDIN JSON field that carries the saved file path SHALL be verified against the current Kiro hook documentation during implementation and recorded in a comment in each Hook_Script.

### Requirement 8: Secret Guard

**User Story:** As the project owner, I want every saved file and every tracked file scanned for API keys, so that no key reaches the public repository.

#### Acceptance Criteria

1. THE Hook_Files SHALL define the Secret_Guard with trigger PostFileSave, no matcher (all files), a command that runs `scripts/hooks/secret_guard.sh`, and a timeout of at most 30 seconds.
2. THE Secret_Guard SHALL detect at least these Secret_Patterns: `sk-[A-Za-z0-9_-]{20,}` (OpenAI-style and DeepSeek-style keys), `AIza[0-9A-Za-z_-]{35}` (Google keys), `-----BEGIN [A-Z ]*PRIVATE KEY-----`, and the generic pattern `api[_-]?key\s*[:=]\s*\S{16,}` matched case-insensitively.
3. WHEN the Secret_Guard runs in save mode, THE Secret_Guard SHALL read the saved file path from the hook event JSON or from its first argument and scan only that file.
4. WHEN the Secret_Guard is run with `--all`, THE Secret_Guard SHALL scan every file listed by `git ls-files` and report the findings of all files in one run.
5. THE Secret_Guard SHALL skip files that git ignores (including `.env`), binary files, and files that no longer exist.
6. THE Secret_Guard SHALL NOT report a line in `.env.example` whose value is empty or a placeholder enclosed in angle brackets.
7. THE Secret_Guard SHALL NOT report a generic-pattern match on a line that contains the Allow_Marker, and SHALL report matches of every other Secret_Pattern on such a line.
8. WHEN the Secret_Guard finds a match, THE Secret_Guard SHALL print one line per finding in the form `<relative path>:<line number>: <pattern name>: <Masked_Value>`, and SHALL exit with a non-zero status after reporting all findings.
9. THE Secret_Guard SHALL never print, log or write the full matched value or any unmasked part of it other than its last 4 characters.
10. WHEN the Secret_Guard finds no match, THE Secret_Guard SHALL exit with status 0 and print nothing in save mode, and print a single line stating the number of scanned files in `--all` mode.
11. THE Hook_Scripts SHALL run under bash 3.2 (macOS default) and bash 5 (Linux), and SHALL NOT depend on GNU-only command options such as `grep -P` or `sed -i` without a suffix.
12. WHEN the Secret_Guard runs in save mode, THE Secret_Guard SHALL write its complete output of the latest run, containing only Masked_Values, to `logs/hooks/secret-guard.log`, overwriting the previous run. WHEN it finds a match, it SHALL print after the finding lines a single summary line that states the number of findings and the log file path.

### Requirement 9: Dev-Time MCP Configuration

**User Story:** As a developer, I want Kiro's development agent to query the Industrial MCP Server directly, so that I can explore and debug the simulated factory data while building the investigation agent.

#### Acceptance Criteria

1. THE Dev_MCP_Config SHALL register exactly four servers under `mcpServers`, named `industrial-mcp-ds-00`, `industrial-mcp-ds-01`, `industrial-mcp-ds-02` and `industrial-mcp-ds-03`. Each server SHALL use command `uv` and args `run python -m industrial_mcp --dataset <id> --data-dir data`, where `<id>` is the Dataset_ID in the server name, and SHALL be enabled by default.
2. THE Dev_MCP_Config SHALL contain no Secret_Value and no environment variable that points to a Ground_Truth_File.
3. IF the Dataset `data/<id>/` of a registered server does not exist when Kiro starts that server, THEN THE Industrial_MCP_Server SHALL fail with its documented error, and THE README SHALL state that `make seed` must run before the dev-time MCP server is used.
4. THE README and the Kiro_Usage_Doc SHALL distinguish the dev-time path (Kiro's agent connects to the Industrial_MCP_Server through the Dev_MCP_Config) from the runtime path (the backend starts one Industrial_MCP_Server session per Dataset), and SHALL state that the runtime path does not use the Dev_MCP_Config.
5. THE Dev_MCP_Config SHALL NOT list `run_simulated_verification` in the auto-approve setting of any registered server, so that Kiro asks the developer before every simulated verification it runs.

### Requirement 10: Container Images

**User Story:** As a judge, I want small, self-contained backend and frontend images, so that the demo runs from a clean clone without local toolchains.

#### Acceptance Criteria

1. THE Backend_Image SHALL be based on `python:3.11-slim`, SHALL install dependencies with uv from `uv.lock` without the development group, and SHALL contain the packages `factory_data`, `simulator`, `industrial_mcp` and `backend`, and none of `frontend/`, `tests/`, `evaluation/`, `.env` or any Dataset.
2. THE Backend_Image SHALL run as a non-root user that owns `/app/data`, `/app/var` and `/app/logs`, and SHALL create these directories in the image so that empty named volumes mounted there inherit that ownership.
3. WHEN a Backend_Image container starts, THE Entrypoint SHALL check each Dataset_ID `ds-00`, `ds-01`, `ds-02` and `ds-03` in DATA_DIR, and for each Dataset whose directory lacks any of `factory.db`, `world_state.json` or `ground_truth.json`, SHALL run `python -m simulator generate` with the matching scenario and the Scenario_Registry default seed, producing all three artifacts.
4. THE Entrypoint SHALL leave every complete Dataset unchanged, so that container restarts keep the existing Datasets and their verification-origin records.
5. IF Dataset generation fails, THEN THE Entrypoint SHALL print the failing Dataset_ID and exit with a non-zero status without starting the API.
6. WHEN all Datasets are complete, THE Entrypoint SHALL start uvicorn with `backend.api.app:app` on host `0.0.0.0` and port 18474 as the container's main process, so that it receives stop signals.
7. THE Frontend_Image SHALL build the Frontend_App in a Node 20 build stage with `npm ci` and `npm run build`, and SHALL serve the build output from an `nginx:alpine` stage.
8. THE Frontend_Image nginx configuration SHALL return `index.html` for every non-file path outside `/api/` (SPA history fallback), and SHALL proxy `/api/` to `http://backend:18474` with HTTP/1.1, `proxy_buffering off`, `proxy_cache off` and `proxy_read_timeout` of at least 3600 seconds, so that Server-Sent Events stream without delay or early disconnect.
9. THE Backend_Image and the Frontend_Image SHALL contain no Secret_Value; the LLM API key SHALL reach the backend container only at run time through the Compose_Stack environment.

### Requirement 11: Compose Stack

**User Story:** As a judge, I want one command that starts the whole app, so that I can try Factory CSI in a browser at a known address.

#### Acceptance Criteria

1. THE Compose_Stack SHALL define exactly two services, `backend` (Backend_Image) and `frontend` (Frontend_Image), each with `restart: unless-stopped`.
2. THE Compose_Stack SHALL publish the frontend service on `127.0.0.1:18473` (container port 80), and SHALL publish the backend service only on `127.0.0.1:18474`.
3. THE Compose_Stack SHALL load `.env` into the backend service with `env_file`, and SHALL set in the backend service environment HOST `0.0.0.0`, PORT `18474`, DATA_DIR `/app/data`, APP_DB_PATH `/app/var/app.db`, CHECKPOINT_DB_PATH `/app/var/checkpoints.db` and LOG_DIR `/app/logs`, which take precedence over `.env`.
4. THE Compose_Stack SHALL mount three named volumes on the backend service at `/app/data`, `/app/var` and `/app/logs`, so that Datasets, the App_DB and logs survive container recreation.
5. THE Compose_Stack SHALL define a backend healthcheck that requests `http://127.0.0.1:18474/api/health` using the Python standard library, with a start period of at least 120 seconds to cover first-start Dataset generation, and the frontend service SHALL depend on the backend service with condition `service_healthy`.
6. WHEN a user runs `docker compose up --build` in a clean clone with a `.env` that contains a valid LLM key, THE Compose_Stack SHALL serve a working app at `http://localhost:18473` on which the Scenario A demo path of the Demo_Script can be completed.
7. WHEN a user runs `docker compose up --build` with a `.env` whose LLM_API_KEY is empty, THE Compose_Stack SHALL start both services, the UI SHALL show the LLM as unavailable with investigation disabled, and the scenario list and Dataset overview SHALL work.
8. THE Compose_Stack SHALL define no service, port or setting that requires a public host name, so that a later deployment can add HTTPS and a public bind address without changing the images.

### Requirement 12: Evaluation Harness Execution

**User Story:** As the project owner, I want an automated harness that runs real investigations on the anomaly scenarios and scores them against the answer key, so that I can report measured behavior instead of impressions.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL be the top-level package `evaluation/` with entry point `python -m evaluation`, and SHALL accept `--runs N` (integer 1 to 10, default 3) and `--datasets` (a comma-separated subset of `ds-01`, `ds-02`, `ds-03`, default all three).
2. IF `--runs` or `--datasets` has an invalid value, THEN THE Evaluation_Harness SHALL print an error naming the option and the allowed values, and exit with status 2 without calling the LLM.
3. WHEN the Evaluation_Harness starts, THE Evaluation_Harness SHALL run the Investigation_Engine LLM health check. IF the LLM_Health_Status is not OK, THEN THE Evaluation_Harness SHALL print a message containing the status, the configured model and the sanitized reason, write no Results_File, and exit with status 2.
4. THE Evaluation_Harness SHALL use the working directory `var/eval/` for its Dataset copies, App_DB and checkpoint database, SHALL generate the selected Datasets there with the Scenario_Registry default seeds at start, and SHALL NOT modify `data/` or `var/app.db`.
5. WHEN the Evaluation_Harness starts an Evaluation_Run, THE Evaluation_Harness SHALL first reset that Dataset with the Reset_Function, so that every Evaluation_Run starts from the generated state with no verification-origin records.
6. THE Evaluation_Harness SHALL execute each Evaluation_Run in-process through the Investigation_Engine and Verification_Loop graph with a real LLM and real Industrial_MCP_Server sessions, answering every approval request with the Auto_Approve_Policy.
7. THE Evaluation_Harness SHALL run the Evaluation_Runs sequentially in the order of the selected Datasets, N runs per Dataset.
8. IF an Evaluation_Run exceeds a wall-clock limit of 900 seconds, or the Case ends in a failed status, THEN THE Evaluation_Harness SHALL record the run with status `timed_out` or `failed` and the error message, count every pass/fail metric of that run as failed, and continue with the next run.
9. THE Evaluation_Harness SHALL be the only package outside `tests/` and `simulator` that reads Ground_Truth, and SHALL read it only to score runs after each Evaluation_Run has finished, never passing Ground_Truth content to the Investigation_Engine.
10. THE Evaluation_Harness SHALL exit with status 0 when all Evaluation_Runs were executed and the outputs were written, regardless of metric results, and with status 1 on a harness error such as an unhandled exception in harness code, a Dataset generation failure or an output write failure.
11. WHILE the Evaluation_Harness is running, THE Evaluation_Harness SHALL print one progress line per Evaluation_Run start and finish, including the Dataset_ID, run index, status and duration.

### Requirement 13: Evaluation Metrics

**User Story:** As the project owner, I want precisely defined per-run metrics, so that evaluation results are reproducible and comparable between versions.

#### Acceptance Criteria

1. THE Evaluation_Harness SHALL record `anomaly_detected` as true when the set of equipment flagged by the Investigation_Engine anomaly detection contains every expected anomaly equipment in the Ground_Truth. For `ds-03` the expected flagged equipment is EOL-B (the surface signal).
2. THE Evaluation_Harness SHALL record `conclusion_acceptable` as true when the final Conclusion_Category matches an Acceptable_Conclusion of the Ground_Truth and the final Support_Level is less than or equal to that entry's maximum Support_Level.
3. THE Evaluation_Harness SHALL record `citation_validity_rate` as the number of cited Evidence_IDs that exist in the Evidence_Registry divided by the number of cited Evidence_IDs in all LLM outputs of the run, and as null when the run cited no Evidence_ID.
4. THE Evaluation_Harness SHALL record `dropped_citations` as the number of citations the Investigation_Engine dropped as invalid during the run, taken from the Case audit records.
5. THE Evaluation_Harness SHALL record `proposal_legality_rate` as the number of Verification_Proposals accepted by the Proposal_Validator divided by the number of Verification_Proposals generated, and as null when none were generated.
6. THE Evaluation_Harness SHALL record, for each executed verification, its verification type, its outcome and the Ground_Truth expected outcome for that verification type, and SHALL record `verification_outcomes_match` as true when every executed verification with an expected outcome has an equal outcome, and as null when no executed verification has an expected outcome.
7. THE Evaluation_Harness SHALL record `state_updated` as true when, for every executed verification, at least one Judgment_Change of that verification round lists that verification's Evidence_ID in its because field, and as null when no verification was executed.
8. THE Evaluation_Harness SHALL record `report_complete` as true when the Case has a full-form Report with all 10 sections in the order defined by the verification-loop spec, every Evidence_ID in the Report exists in the Evidence_Registry, and the Banned_Wording_Checker finds no banned phrase in the rendered Markdown. A Case without a Report SHALL record false.
9. THE Evaluation_Harness SHALL record `duration_seconds` (wall clock from Case start to final status), `llm_calls`, `tokens_in`, `tokens_out` and `estimated_cost_usd`, where the cost is computed with LiteLLM cost tracking and is null when LiteLLM cannot price the configured model.
10. THE Evaluation_Harness SHALL treat a rate metric as passed only when it equals 1.0, `dropped_citations` as passed only when it equals 0, and a boolean metric as passed only when it is true. A null metric SHALL count as not applicable and SHALL be excluded from that metric's pass count denominator.
11. THE Evaluation_Harness SHALL compute every metric with deterministic code from the recorded Case state, audit records, Evidence_Registry, Report and Ground_Truth, and SHALL NOT use an LLM to score a run.
12. THE Evaluation_Harness SHALL compute the Run_Metrics from the persisted Case events and the Case detail, using the canonical Case event catalog owned by the investigation-api spec: the anomaly detection result recorded in an `evidence_added` event and in the anomaly field of the Case detail (criterion 1), `citation_dropped` (criteria 3 and 4), `proposal_rejected_by_validator` (criterion 5), `verification_executed` (criterion 6), `judgment_changed` (criterion 7), `conclusion_finalized` (criterion 2), `report_generated` (criterion 8) and `llm_call` (criterion 9).

### Requirement 14: Evaluation Outputs

**User Story:** As a judge, I want a readable evaluation summary with honest limitations, so that I can judge how reliably the agent behaves on the provided scenarios.

#### Acceptance Criteria

1. WHEN all Evaluation_Runs have finished, THE Evaluation_Harness SHALL write the Results_File named with the harness start time in UTC as `YYYYMMDDTHHMMSSZ.json`, containing the harness start and end UTC_Timestamps, the git commit hash, the LLM provider and model, the runs per Dataset, every Evaluation_Run with its status, Run_Metrics and executed verification details, and the per-Dataset aggregates.
2. THE Evaluation_Harness SHALL write the Latest_Summary with the same header fields and per-Dataset aggregates as the Results_File and without per-run details, replacing the previous Latest_Summary.
3. THE Evaluation_Harness SHALL generate the Evaluation_Report with one table per Dataset that lists, for each pass/fail metric, the number of passed runs and the number of applicable runs, and SHALL list the mean and median `duration_seconds`, the mean `llm_calls`, the total tokens in and out and the total estimated cost per Dataset.
4. THE Evaluation_Report SHALL contain the Limitations_Statement with N replaced by the runs per Dataset, the generation UTC_Timestamp, the git commit hash, the model and the Results_File name.
5. THE Evaluation_Report SHALL identify Datasets by Dataset_ID and Scenario_Registry label, and SHALL contain no affected SN list, Anomaly_Window timestamp or expected verification outcome from the Ground_Truth.
6. THE Results_File, the Latest_Summary and the Evaluation_Report SHALL contain no Secret_Value, and the Evaluation_Harness SHALL write them only after all Evaluation_Runs have finished, so that an interrupted invocation leaves the previous Latest_Summary and Evaluation_Report unchanged.

### Requirement 15: README

**User Story:** As a judge, I want a complete English README, so that I understand what Factory CSI does and can run it in a few minutes.

#### Acceptance Criteria

1. THE README SHALL be written in English and SHALL start with the project name and a pitch of at most three sentences, followed by these level-2 sections in this order: The Problem, What It Does, Architecture, Screenshots, Quick Start (Docker), Local Development, Configuring the LLM, Scenarios, Tests, Evaluation, Project Structure, Safety and Limitations, How Kiro Was Used, License.
2. THE What It Does section SHALL describe the three innovations: cross-system manufacturing forensics, evidence-grounded investigation and next best verification with human approval.
3. THE Architecture section SHALL contain a Mermaid diagram of the frontend, backend API, investigation graph, LLM provider via LiteLLM, MCP client, Industrial_MCP_Server and simulated factory data, and a list of these components with one sentence each, and SHALL link to the Architecture_Doc.
4. THE Screenshots section SHALL contain real screenshots of the running app committed under `docs/images/` before submission, and SHALL contain no mock-up presented as a screenshot.
5. THE Quick Start (Docker) section SHALL list the steps `cp .env.example .env`, setting LLM_API_KEY, `docker compose up --build` and opening `http://localhost:18473`, and SHALL state what the app shows without a key.
6. THE Local Development section SHALL list `make setup`, `make seed`, `make dev-backend` and `make dev-frontend` in separate terminals, the required tool versions, and the dev-time MCP note of Requirement 9 criterion 3.
7. THE Configuring the LLM section SHALL explain the LLM settings, the LiteLLM model string format, how to switch between the providers listed in Requirement 5 criterion 4, and that no fallback mode exists.
8. THE Scenarios section SHALL contain a table with Dataset_ID, Scenario_Registry label and Scenario_Registry description for the four Datasets, and SHALL contain no Ground_Truth content such as expected conclusions, affected SNs or expected verification outcomes.
9. THE Tests section SHALL state that `make test-fast` needs no key, and that `make test` needs a valid key in `.env` and costs a few cents per run.
10. THE Safety and Limitations section SHALL state that all data is fictional, that verification results are simulated, that the system is decision support and not an automated root-cause verdict, that it controls no real equipment, that it is not certified for production quality decisions, and that the demo has no authentication and is meant for local use.
11. THE How Kiro Was Used section SHALL summarize the Kiro features used and link to the Kiro_Usage_Doc, and the License section SHALL name MIT and link to LICENSE.

### Requirement 16: Architecture, Demo Script and Submission Documents

**User Story:** As the project owner, I want architecture, demo and submission documents, so that judges can understand the design, the video follows a tested script and the Devpost text is ready to paste.

#### Acceptance Criteria

1. THE Architecture_Doc SHALL contain a component diagram, the investigation graph diagram including the human approval interrupt, the data model of the Factory_DB and the App_DB, the contract (name, inputs, outputs, errors) of every Industrial_MCP_Server tool, and the list of `/api/*` endpoints with method and purpose, consistent with the other six specs.
2. THE Demo_Script SHALL define a shot list with a total length of at most 175 seconds, organized in these beats: 0–25 s problem; 25–75 s automatic investigation with visible MCP tool calls; 75–125 s next best verification, approval of a cross_retest and the resulting Judgment_Change; 125–160 s report; 160–175 s Kiro specs, steering, hooks and MCP.
3. THE Demo_Script SHALL map each beat to the concrete UI actions on Scenario A (`ds-01`) after a Dataset reset, the expected visible result, and the narration text, and SHALL list the preconditions (valid key in `.env`, Compose_Stack running, Dataset reset).
4. THE Submission_Draft SHALL be written in English and SHALL contain the sections Inspiration, What It Does, How We Built It, Challenges We Ran Into, Accomplishments That We Are Proud Of, What We Learned and What's Next, the category Frankenstein, and placeholders `<REPO_URL>`, `<VIDEO_URL>` and `<APP_URL>`, with a note that the app URL is deferred.
5. THE Submission_Draft SHALL describe the features, the innovation and how Kiro was used, and SHALL contain a manual checklist of the competition rules: code built during Oct 30 – Dec 4, 2026, built with Kiro, public repository with an OSI-approved license, `.kiro/` committed at the root, install and run instructions, working app URL, public YouTube demo shorter than 3 minutes, English description, no judge test account needed because the MVP has no login, and the deadline Dec 4, 2026 14:00 PST.
6. THE Submission_Draft SHALL state that the latest official competition rules take precedence over the checklist.

### Requirement 17: Development Log and Kiro Usage Documentation

**User Story:** As a judge, I want a truthful record of how the project was built with Kiro, so that I can assess the use of Kiro from facts and not claims.

#### Acceptance Criteria

1. THE Dev_Log SHALL contain chronological entries, and an entry SHALL be appended at the end of each implementation phase with the UTC date, the spec and task identifiers covered, what was done, the Kiro features used, the problems met and their fixes, and the verification commands run with their results.
2. THE Dev_Log SHALL contain only entries about work that actually happened, and SHALL NOT be pre-filled with planned or invented entries.
3. THE Kiro_Usage_Doc SHALL describe the Kiro features actually used (Specs, Steering, Hooks, MCP, and agent chat or Autopilot), how the seven specs decomposed the work, how the hooks improved testing with concrete examples referenced to Dev_Log entries, and how the Industrial_MCP_Server was developed and debugged with Kiro.
4. THE Kiro_Usage_Doc SHALL make every claim traceable to a file in `.kiro/` or to a Dev_Log entry, and SHALL contain a number (time saved, test count, defect count) only when the Dev_Log records how it was measured.
5. THE Kiro_Usage_Doc SHALL NOT describe a Kiro feature that the project did not use.

### Requirement 18: Pre-Submission Checker

**User Story:** As the project owner, I want one command that checks the submission rules I can verify locally, so that I do not miss a requirement before the deadline.

#### Acceptance Criteria

1. THE Submission_Checker SHALL check that LICENSE exists, starts with `MIT License` and contains the MIT permission text.
2. THE Submission_Checker SHALL check that `.kiro/specs/` contains at least one `requirements.md`, `.kiro/steering/` contains at least one `.md` file, `.kiro/hooks/` contains at least one `.json` file, that these files are tracked by git, and that `git check-ignore` reports none of them as ignored.
3. THE Submission_Checker SHALL check that `secret_guard.sh --all` exits with status 0.
4. THE Submission_Checker SHALL check that `.env` is not tracked by git and that `.env.example` is tracked.
5. THE Submission_Checker SHALL check that the README contains every level-2 section heading listed in Requirement 15 criterion 1.
6. THE Submission_Checker SHALL check that the Demo_Script and the Kiro_Usage_Doc exist and are non-empty.
7. THE Submission_Checker SHALL check that `lint-imports` exits with status 0 and that `pytest -m "not llm"` exits with status 0.
8. THE Submission_Checker SHALL run every check even when an earlier check fails, print one line per check in the form `PASS <check name>` or `FAIL <check name>: <reason>`, print a final summary line with the number of passed and failed checks, and exit with a non-zero status if any check failed.
9. THE Submission_Checker SHALL run without an LLM API key and without network access to an LLM provider.

### Requirement 19: Clean-Clone Verification and Optional CI

**User Story:** As the project owner, I want to prove that a fresh clone builds and passes its tests, so that judges do not hit missing files or undeclared dependencies.

#### Acceptance Criteria

1. THE Clean_Clone_Script SHALL clone the Repository (default: the local repository at its current HEAD commit; optionally a URL given as the first argument) into a new temporary directory and run `make setup`, `make seed` and `make test-fast` there without a `.env` file.
2. THE Clean_Clone_Script SHALL print the cloned commit hash and the result of each step, exit with a non-zero status if any step fails, and print the temporary directory path when it keeps it for inspection after a failure.
3. THE Clean_Clone_Script SHALL warn that uncommitted changes in the working tree are not part of the clone.
4. THE README or the Dev_Log SHALL document the manual follow-up: in the clean clone, create `.env` with a valid key, run `docker compose up --build`, and complete the Scenario A path of the Demo_Script at `http://localhost:18473`.
5. WHEN the clean-clone verification (scripted and manual parts) is performed, THE Dev_Log SHALL record its date, the commit hash, the result of each step and any problem found.
6. WHERE the optional CI_Workflow is implemented (priority P1), THE CI_Workflow SHALL run on push and pull request on `ubuntu-latest` with Python 3.11, uv and Node 20, and SHALL run `make setup`, `make seed`, `make test-fast` and `make check-submission`.
7. WHERE the optional CI_Workflow is implemented, THE CI_Workflow SHALL reference no repository secret and SHALL run no LLM_Test.

### Requirement 20: Tooling Tests

**User Story:** As a developer, I want deterministic tests for the hook scripts, the submission checker and the evaluation metrics, so that the delivery tooling stays correct as the project changes.

#### Acceptance Criteria

1. THE Deterministic_Tests in `tests/unit/tooling/` SHALL verify the Test_Hook mapping of Requirement 7 criterion 4 through `--print-targets` for at least one path per mapping rule, a path under `tests/`, and an unmapped path.
2. THE Deterministic_Tests SHALL verify that the Secret_Guard reports each Secret_Pattern of Requirement 8 criterion 2 in a temporary file, prints the Masked_Value with only the last 4 characters visible, never prints the full value, ignores `.env.example` placeholder lines, honors the Allow_Marker only for the generic pattern, and exits with status 0 on a clean file.
3. THE Deterministic_Tests SHALL build every fake key at run time (for example by string concatenation), so that no test file in the Repository contains a literal that matches a Secret_Pattern and `secret_guard.sh --all` passes on the Repository.
4. THE Deterministic_Tests in `tests/eval/` SHALL verify each metric of Requirement 13 on hand-built Case fixtures, including the null and not-applicable cases, a dropped citation, an illegal proposal, a mismatched verification outcome, a missing Judgment_Change and a Report with a banned phrase.
5. THE Deterministic_Tests SHALL verify that the Evaluation_Report generated from a fixture Results_File contains the Limitations_Statement with the fixture's N and contains no Ground_Truth affected SN, Anomaly_Window timestamp or expected verification outcome.
6. THE Deterministic_Tests SHALL verify that the Evaluation_Harness exits with status 2 and writes no Results_File when the LLM health check returns a status other than OK, using a stubbed health check.
7. THE Deterministic_Tests SHALL verify that the root `.gitignore` leaves `.kiro/` files, `.env.example`, `factory_data/` and `evaluation/results/latest-summary.json` unignored and ignores `.env`, `/data/`, `/var/` and `/logs/`, using `git check-ignore`.
8. THE tooling tests SHALL pass with network access disabled and without an LLM API key.
