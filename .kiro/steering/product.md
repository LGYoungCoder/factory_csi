---
inclusion: always
---
# Product: Factory CSI

Factory CSI is an AI Manufacturing Quality Investigation Copilot, built for the Kiroween 2026 hackathon in the **Frankenstein** category. It combines industrial data systems, MCP, statistical quality analytics, an LLM agent and human-in-the-loop verification.

- **Target user:** a manufacturing quality engineer investigating a sudden rise in End-of-Line (EOL) defects.
- **Purpose:** start from one quality anomaly, collect real (simulated) evidence across MES, PPM and EOL through MCP, generate hypotheses that cite evidence, propose the next verification, run it after human approval, revise the judgment and write a traceable report.
- **Three innovations:** (1) cross-system manufacturing forensics, (2) evidence-grounded investigation (every claim cites Evidence IDs that resolve to records), (3) Next Best Verification (the AI proposes what to check next and updates its judgment on the result).
- **Scenarios (UI labels only, never shown to the LLM):** "Baseline – Normal Operation" (ds-00), "Scenario A – EOL Tester Drift" (ds-01), "Scenario B – Manufacturing Process Defect" (ds-02), "Scenario C – Insufficient Evidence" (ds-03).
- **Nature of the data:** the factory (Factory Alpha, Line A) is fictional, all data is generated, and verifications are simulated. Results are decision support, not certified root causes. The product contains no real company data or trademarks.
- **UI language:** English. Docs: English.
