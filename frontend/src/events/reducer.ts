import type { CaseEvent } from "@/api/types";

/** Graph node → progress step. Unknown nodes do not move the stepper. */
export const STEPS = ["Load", "Detect", "Collect", "Analyze", "Hypotheses", "Propose", "Approval", "Verify", "Update", "Report"] as const;
export const NODE_STEP: Record<string, number> = {
  load_case: 0,
  detect_anomaly: 1,
  collect_evidence: 2,
  analyze_evidence: 3,
  generate_hypotheses: 4,
  propose_verification: 5,
  execute_verification: 7,
  update_hypotheses: 8,
  finalize_conclusion: 9,
  generate_report: 9,
};

export const KNOWN_TYPES = new Set([
  "status_changed", "node_started", "node_completed", "mcp_call", "llm_call", "anomaly_detected", "evidence_added",
  "hypotheses_updated", "support_downgraded", "citation_dropped", "awaiting_approval", "proposal_rejected_by_validator",
  "decision_recorded", "verification_executed", "verification_failed", "judgment_changed", "judgment_change_unattributed",
  "conclusion_support_capped", "conclusion_finalized", "report_generated", "budget_exhausted", "error", "audit", "completed",
]);

export type LiveState = {
  lastSeq: number;
  events: CaseEvent[];
  currentNode: string | null;
  currentStep: number;
  maxStep: number;
  status: string | null;
  finished: boolean;
  warnings: string[];
  audit: CaseEvent[];
};

export const initialLive: LiveState = {
  lastSeq: 0, events: [], currentNode: null, currentStep: -1, maxStep: -1, status: null, finished: false, warnings: [], audit: [],
};

export type LiveAction = { type: "event"; event: CaseEvent } | { type: "reset" } | { type: "snapshot"; status: string; lastSeq: number };

/** Pure reducer: ordering by seq, dedupe, every catalog type handled; unknown types are ignored. */
export function liveReducer(state: LiveState, action: LiveAction): LiveState {
  if (action.type === "reset") return initialLive;
  if (action.type === "snapshot") {
    const finished = ["COMPLETED", "FAILED", "FAILED_LLM"].includes(action.status);
    return { ...state, status: action.status, finished: state.finished || finished };
  }
  const e = action.event;
  if (e.seq <= state.lastSeq || !KNOWN_TYPES.has(e.type)) return e.seq > state.lastSeq ? { ...state, lastSeq: e.seq } : state;
  const next: LiveState = { ...state, lastSeq: e.seq, events: [...state.events, e].slice(-400) };
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "node_started": {
      const node = String(p.node);
      next.currentNode = node;
      if (node in NODE_STEP) {
        next.currentStep = NODE_STEP[node];
        next.maxStep = Math.max(state.maxStep, NODE_STEP[node]);
      }
      break;
    }
    case "awaiting_approval":
      next.currentNode = "human_approval";
      next.currentStep = 6;
      next.maxStep = Math.max(state.maxStep, 6);
      break;
    case "status_changed":
      next.status = String(p.to);
      break;
    case "completed":
      next.status = String(p.final_status);
      next.finished = true;
      next.currentNode = null;
      if (p.final_status === "COMPLETED") {
        next.currentStep = STEPS.length;
        next.maxStep = STEPS.length;
      }
      break;
    case "citation_dropped":
      next.warnings = [...state.warnings, `Dropped invalid citation(s) ${(p.invalid_ids as string[] | undefined)?.join(", ") ?? ""} in ${String(p.item)}`];
      break;
    case "budget_exhausted":
      next.warnings = [...state.warnings, `Budget exhausted: ${String(p.budget)}`];
      break;
    case "proposal_rejected_by_validator":
      next.warnings = [...state.warnings, `A proposal was rejected by the validator: ${String(p.reason)}`];
      break;
    case "audit":
      next.audit = [...state.audit, e];
      break;
    default:
      break;
  }
  return next;
}

/** Events that should trigger a refetch of the case snapshot. */
export const REFRESH_TYPES = new Set([
  "status_changed", "anomaly_detected", "evidence_added", "hypotheses_updated", "awaiting_approval", "verification_executed",
  "judgment_changed", "conclusion_finalized", "report_generated", "completed", "error",
]);
