# Devpost submission draft

**Project:** Factory CSI – AI Manufacturing Quality Investigation Copilot
**Category:** Frankenstein
**Links:** repository `<github-url>` · video `<youtube-url>` · app `<app-url (to be deployed)>`

## Inspiration
In automotive component plants, a sudden jump in end-of-line test failures triggers hours of manual forensics across MES, equipment monitoring and test systems. The hardest part is not finding data. It is knowing which check to run next, and avoiding a confident wrong verdict when a tester is drifting or the product mix changed.

## What it does
Factory CSI investigates an EOL quality anomaly on a fictional production line:
- It detects the anomaly statistically and queries simulated MES, PPM and EOL systems through an Industrial MCP Server.
- It turns every statistical finding into a citable Evidence item that links to raw records.
- It proposes ranked hypotheses whose support level is enforced by rules.
- It proposes the **Next Best Verification**: a cross retest, a reference sample check or a configuration audit, with the expected effect of each outcome on each hypothesis.
- After a human approves, it runs the simulated check, updates its judgment with an explicit before → after change, and writes a 10-section traceable report.
- When evidence is missing, it says "insufficient evidence".

## How we built it
- Kiro specs (7 modules), steering, hooks and MCP.
- Python: a seed-reproducible scenario generator with a hidden world state and an answer key, isolated by import contracts.
- An Industrial MCP Server built on the official MCP SDK (stdio).
- Deterministic analytics with SciPy and a LangGraph state graph with `interrupt()`-based human approval and SQLite checkpoints.
- LiteLLM, so any provider works (DeepSeek by default).
- FastAPI with Server-Sent Events, a React + TypeScript + ECharts workspace, and Docker Compose.

## Challenges we ran into
- Designing scenario physics so that each case is statistically detectable yet still ambiguous enough to require verification. We added a "no-flip" measurement rule, then searched seeds against the spec's acceptance criteria.
- Keeping the LLM honest: citation validation, schema repair, support caps, and no fallback text when the model fails.
- Building on MCP SDK 2.x and LangGraph 1.x while their APIs were new.

## Accomplishments
- A full loop from anomaly to verification to updated judgment and report, running against a real LLM.
- An evaluation harness scored against the hidden ground truth (see `docs/evaluation.md`).

## What we learned
Separating what the code computes from what the model interprets makes an industrial AI agent auditable. A "next verification" step is more useful to engineers than another dashboard.

## What's next
Connectors for real MES / QMS systems via MCP, more failure modes, authentication and a hosted demo.
