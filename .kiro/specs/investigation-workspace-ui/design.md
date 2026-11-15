# Design Document – Investigation Workspace UI

The shared design is in [docs/architecture.md](../../../docs/architecture.md), section 9.

## Structure
```text
frontend/src/
  api/        client.ts (fetch + ApiError), types.ts, queries.ts (TanStack Query hooks)
  events/     reducer.ts (pure), useCaseEvents.ts (EventSource + reconnect)
  components/ TopBar, LlmIndicator, ScenarioPanel, LineTopology, EquipmentDrawer,
              AnomalyCard, TrendCharts, EvidenceTimeline, EvidenceDrawer, ProgressStepper,
              InvestigatorPanel, McpCallList, HypothesisCard, DecisionPanel, JudgmentChanges,
              ConclusionCard, ui/ (button, badge, dialog, drawer, tooltip, tabs)
  pages/      Workspace.tsx, ReportPage.tsx
  lib/        format.ts, status.ts
```

## Key decisions
- Dark theme tokens are in `tailwind.config` (slate base, sky/emerald accents, amber/red only for warnings and anomalies).
- The UI uses small local shadcn-style components (Radix primitives) instead of the CLI generator, so the build stays reproducible offline.
- Server state lives in TanStack Query. Live case state is the case snapshot merged with the reducer over SSE events.
