# Implementation Plan

- [ ] 1. LLM layer
  - Settings, LiteLLM client with budget accounting and call records, health check, redaction, structured output with repairs, MCP → tool schema conversion.
  - _Requirements: 1, 2, 3, 4, 5_
- [ ] 2. Deterministic analytics
  - detect_anomaly, comparisons and stratification, process change, MSA (reference and retests), timeline.
  - _Requirements: 6, 7, 8, 9, 10, 11_
- [ ] 3. Evidence registry, citations, hypotheses and guardrails
  - _Requirements: 12, 13, 14, 15, 16_
- [ ] 4. Graph segment 1
  - State, load_case, detect_anomaly, collect_evidence (fixed calls + tool loop), analyze_evidence, generate_hypotheses, budgets, checkpointing, events, failure handling.
  - _Requirements: 17, 18, 19, 20, 21_
- [ ] 5. Module tests (deterministic + `llm`)
  - _Requirements: 22_
