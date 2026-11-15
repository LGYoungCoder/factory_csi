# Evaluation

Generated 2026-11-15T18:06:15Z with `deepseek/deepseek-flash` by `make eval` (auto-approve the rank-1 proposal, max 3 verification rounds).

> Limitations: 3 synthetic scenarios, 3 runs each; not evidence of production-grade root-cause accuracy. All data is simulated by the project's own generator.

| Metric | Scenario A – EOL Tester Drift | Scenario B – Manufacturing Process Defect | Scenario C – Insufficient Evidence |
|---|---|---|---|
| Completed runs | 3/3 | 3/3 | 3/3 |
| Anomaly detection correct | 3/3 | 3/3 | 3/3 |
| Conclusion acceptable (category and support ≤ allowed) | 3/3 | 3/3 | 3/3 |
| Report complete (10 sections, valid EV ids, no banned wording) | 3/3 | 3/3 | 3/3 |
| Citation validity (mean) | 1.0 | 1.0 | 1.0 |
| Dropped citations (total) | 0 | 0 | 0 |
| Proposal legality (mean) | 1.0 | 1.0 | 1.0 |
| Verification outcome = ground truth (mean, comparable checks) | 1.0 | 1.0 | 1.0 |
| Verification evidence cited by the final hypotheses (mean) | 1.0 | 1.0 | 1.0 |
| Verification that changed a support level, citing it (mean) | 0.333 | 0.333 | 0.222 |
| Duration s (mean / median) | 64.2 / 65.2 | 58.1 / 57.1 | 82.533 / 68.3 |
| LLM calls (mean) | 13.667 | 11.333 | 12.667 |
| MCP calls (mean) | 17.667 | 18.667 | 17.667 |
| Cost USD (mean, LiteLLM estimate) | 0.013 | 0.011 | 0.012 |

## Final conclusions per scenario

- **Scenario A – EOL Tester Drift**: `TESTER_MEASUREMENT_DRIFT/HIGH` ×3
- **Scenario B – Manufacturing Process Defect**: `PROCESS_PARAMETER_DEVIATION/HIGH` ×3
- **Scenario C – Insufficient Evidence**: `PRODUCT_MIX_SHIFT/MEDIUM` ×3

## Per run

| Dataset | Run | Status | Conclusion | Acceptable | Verifications | s | $ |
|---|---|---|---|---|---|---|---|
| ds-01 | 1 | COMPLETED | TESTER_MEASUREMENT_DRIFT/HIGH | True | cross_retest, reference_sample_check, cross_retest | 65.2 | 0.01283 |
| ds-01 | 2 | COMPLETED | TESTER_MEASUREMENT_DRIFT/HIGH | True | cross_retest, reference_sample_check, cross_retest | 74.4 | 0.01384 |
| ds-01 | 3 | COMPLETED | TESTER_MEASUREMENT_DRIFT/HIGH | True | cross_retest, reference_sample_check, cross_retest | 53.0 | 0.01147 |
| ds-02 | 1 | COMPLETED | PROCESS_PARAMETER_DEVIATION/HIGH | True | process_config_check, cross_retest, reference_sample_check | 57.1 | 0.01058 |
| ds-02 | 2 | COMPLETED | PROCESS_PARAMETER_DEVIATION/HIGH | True | process_config_check, cross_retest, cross_retest | 55.1 | 0.01015 |
| ds-02 | 3 | COMPLETED | PROCESS_PARAMETER_DEVIATION/HIGH | True | process_config_check, cross_retest, cross_retest | 62.1 | 0.01161 |
| ds-03 | 1 | COMPLETED | PRODUCT_MIX_SHIFT/MEDIUM | True | reference_sample_check, cross_retest, cross_retest | 123.3 | 0.01132 |
| ds-03 | 2 | COMPLETED | PRODUCT_MIX_SHIFT/MEDIUM | True | cross_retest, cross_retest, cross_retest | 56.0 | 0.01078 |
| ds-03 | 3 | COMPLETED | PRODUCT_MIX_SHIFT/MEDIUM | True | cross_retest, reference_sample_check, process_config_check | 68.3 | 0.01315 |

A verification outcome is compared with the ground truth only when it targets the scenario's reference check (e.g. the cross retest on EOL-A or the reference check on the scenario's tester); other checks are counted as not comparable.
