# Demo video script (≤ 175 s)

Setup before recording:
- `make docker-up`; open http://localhost:18473; LLM indicator green.
- Select **Scenario A – EOL Tester Drift** and press **Reset dataset**.
- Browser at 1600×1000 with zoom 100 %.

| Time | Screen / action | Voice-over (EN) |
|---|---|---|
| 0–25 s | Workspace: topology with **EOL-B red**, FAIL_Rate trend (EOL-B dashed line rising from 09:00), anomaly card 1.0 % → 17.1 %. | "Line A of our fictional Factory Alpha. EOL tester B's defect rate jumped from 1 % to 17 %. Is the product bad, is the tester drifting, or did the product mix change? Normally an engineer digs through MES, equipment and EOL systems by hand." |
| 25–75 s | Press **Start Investigation**. Stepper advances. Right panel: MCP tool calls stream in (`get_eol_summary`, `get_reference_sample_checks`, `get_equipment_events`…). Evidence timeline fills. Hypotheses appear (Tester drift Medium, Process Low…). Click one EV chip → drawer with raw EOL records. | "Factory CSI calls our Industrial MCP Server to query the simulated MES, equipment and EOL systems. Statistics are computed deterministically; every finding is an Evidence ID that links to raw records. The AI may only cite those IDs." |
| 75–125 s | **Next Best Verification** card: cross retest of 5 failed SNs on EOL-A, expected-outcomes table. Press **Approve Verification**. Verification evidence (green VERIFICATION) appears; **Judgment changes**: Tester measurement drift Medium → **High** because EV-0xx. | "Instead of guessing, it proposes the next best check and explains how each outcome would change its judgment. I approve a simulated cross retest: all five pass on tester A. Its judgment moves from Medium to High, and it cites the new evidence." |
| 125–160 s | **Conclude Investigation** → conclusion card → **Open report**. Scroll sections 1, 6, 7, 8. Show **Download Markdown** / **Print / Save as PDF**. | "The report shows the anomaly, the timeline, the evidence, which verifications were run and by whom, how they changed the judgment, and the suspected affected products. It's labelled as suspected, never as a confirmed root cause." |
| 160–175 s | Kiro IDE: `.kiro/specs` (7 specs), steering files, hooks panel, `.kiro/settings/mcp.json`. | "Built with Kiro: seven specs, steering, test and secret-guard hooks, and the same MCP server registered for Kiro's own agent." |

Backup take: Scenario C. Reject all once with a reason. The EOL-B reference check returns UNAVAILABLE, and the final conclusion is "Insufficient evidence".
