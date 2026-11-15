# Design Document – Verification Loop

The shared design is in [docs/architecture.md](../../../docs/architecture.md), section 6.

## Components
- `backend/agent/proposals.py`: candidate SN list builder, ProposalSet schema, deterministic validator.
- `backend/agent/nodes_loop.py`: propose_verification, human_approval (`langgraph.types.interrupt`), execute_verification, update_hypotheses, finalize_conclusion.
- `backend/agent/judgment.py`: before/after diff → JudgmentChange.
- `backend/agent/report.py`: deterministic sections 2–8, Markdown renderer with `#evidence-EV-xxx` anchors, banned-wording checker; narrative sections via structured LLM call.

## Key decisions
- Decision validation happens in the API before resuming (`Command(resume=decision)`); the node re-validates as defense in depth.
- approval_id `APR-<case_id>-<round>` is created only inside execute_verification after an approve decision is read from state.
- Conclusion rule and support caps are pure functions (unit-tested without LLM).
