# Implementation Plan

- [ ] 1. Proposals
  - Candidate SN list, ProposalSet schema, propose_verification node, validator.
  - _Requirements: 1, 2, 3, 4_
- [ ] 2. Human approval, decision handling and execution
  - Interrupt payload, decision validation, reject/conclude routing, execute_verification with the approval guard.
  - _Requirements: 5, 6, 7, 8, 9_
- [ ] 3. Hypothesis update, loop control and conclusion
  - _Requirements: 10, 11, 12_
- [ ] 4. Report
  - Deterministic sections, narrative with validation, storage, Markdown rendering.
  - _Requirements: 13, 14, 15_
- [ ] 5. Status model, retry and audit events
  - _Requirements: 16, 17, 18_
- [ ] 6. Module tests (deterministic + `llm`)
  - _Requirements: 19, 20_
