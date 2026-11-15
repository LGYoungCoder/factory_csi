# Manual E2E checklist (local)

Prerequisites: `make seed`, `make dev-backend`, `make dev-frontend`, valid key in `.env`.

## Scenario A (ds-01)
1. Open http://localhost:5173/?ds=ds-01 and press **Reset dataset** (confirm). EOL-B is red ("■ Anomaly") and EOL-A is green.
2. Press **Start Investigation**. The stepper advances. MCP tool calls appear live in the right panel. The evidence timeline fills.
3. Wait for **Next Best Verification**. Check the rationale and the expected outcomes table. Optionally press "Show other suggestions".
4. Press **Approve Verification** on the cross retest. The verification evidence (VERIFICATION) appears and **Judgment changes** shows Tester drift ↑ with "because EV-xxx".
5. Continue or press **Conclude Investigation** (confirm). The conclusion card appears. Use **Open report** → Download Markdown and Print / Save as PDF.
6. Click EOL-B in the topology. The drawer shows reference checks, and related evidence is highlighted in the timeline.

## Scenario C (ds-03)
1. Reset ds-03 and start an investigation.
2. At the first proposal, press **Reject all** and enter a reason. New proposals do not repeat the rejected ones.
3. Approve the reference sample check on EOL-B. Its outcome is UNAVAILABLE ("out for calibration") and appears as absence evidence.
4. The final conclusion is "Insufficient evidence for a conclusion", or a suspected product mix shift at most Medium.

## LLM unavailable
1. Set `LLM_API_KEY=` in `.env` and restart the backend.
2. A red banner appears. **Start Investigation**, Approve and Retry are disabled with tooltips. Overview and trends still work.
