# Implementation Plan

- [x] 1. App shell, API client, theme, top bar and LLM indicator
  - _Requirements: 1, 2, 3, 4, 20, 21_
- [x] 2. Factory overview: scenario panel, reset, line topology, equipment drawer
  - _Requirements: 5, 6, 7_
- [x] 3. Workspace center: anomaly card, trend charts, evidence timeline and drawer, start and progress stepper
  - _Requirements: 8, 9, 10_
- [x] 4. Event stream client and reducer
  - _Requirements: 17, 18_
- [x] 5. AI investigator panel: status line, MCP calls, evidence list, hypotheses, decision panel, judgment changes, conclusion, lifecycle states
  - _Requirements: 11, 12, 13, 14, 15, 16_
- [x] 6. Report view
  - _Requirements: 19_
- [x] 7. Module tests, typecheck, lint, manual E2E checklist
  - _Requirements: 22_
- [x] 8. Chinese UI (added after the initial scope, on user request)
  - `src/i18n.tsx` dictionary + `useI18n()`, EN / 中文 toggle persisted in localStorage, `?lang=zh` URL override; scenario labels and status reasons translated in the UI; AI-generated text and report body stay English.
  - Test: every literal `t("…")` key in components/pages has a Chinese entry.
