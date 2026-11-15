export type LlmStatus = {
  status: "OK" | "UNAVAILABLE" | "MISCONFIGURED";
  model: string;
  provider: string;
  checked_at: string | null;
  reason: string | null;
};

export type Scenario = { dataset_id: string; key: string; label: string; description: string; available: boolean };

export type EquipmentStatus = {
  equipment_id: string;
  status: "GREEN" | "ORANGE" | "RED" | "GREY";
  reasons: { code: string; message: string }[];
};

export type TesterAnomaly = {
  equipment_id: string;
  baseline_rate: number;
  window_rate: number;
  baseline_counts: [number, number];
  window_counts: [number, number];
  p_value: number;
  flagged: boolean;
};

export type AnomalyResult = {
  status: "ANOMALY" | "NO_ANOMALY";
  anomalies: TesterAnomaly[];
  testers: TesterAnomaly[];
  detected_window: { start: string; end: string };
  baseline_window: { start: string; end: string };
};

export type Overview = {
  dataset_id: string;
  mode: string;
  factory: string;
  line: string;
  data_time_range: { start: string; end: string };
  record_counts: Record<string, number>;
  equipment_status: EquipmentStatus[];
  fail_rates: Record<string, { last_60_min: number | null; full_range: number | null }>;
  overall_fail_rate: number | null;
  anomaly_detection: AnomalyResult;
};

export type Trends = {
  bucket_minutes: number;
  fail_rate: { tester_id: string; bucket_start: string; test_count: number; fail_count: number; fail_rate: number | null }[];
  st20: { bucket_start: string; parameter: string; program_version: string; count: number; mean: number; p5: number; p95: number }[];
  reference_deviations: Record<string, { ts: string; deviation: number; result: string; origin: string }[]>;
  process_changes: { change_id: string; equipment_id: string; ts: string; change_type: string; old_value: string; new_value: string }[];
};

export type Evidence = {
  id: string;
  kind: "statistic" | "event" | "record" | "verification" | "absence";
  source_system: "MES" | "PPM" | "EOL" | "ANALYTICS" | "VERIFICATION";
  title: string;
  summary: string;
  data: Record<string, unknown>;
  record_refs: string[];
  mcp_call_ids: string[];
  ts: string | null;
  equipment: string[];
  created_at: string;
};

export type Support = "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT";

export type Hypothesis = {
  hypothesis_id: string;
  category: string;
  title: string;
  statement: string;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  missing_evidence: string[];
  support: Support;
  recommended_verification_types: string[];
  change_rationale?: string | null;
};

export type Proposal = {
  proposal_id: string;
  rank: number;
  verification_type: "cross_retest" | "reference_sample_check" | "process_config_check";
  params: Record<string, unknown>;
  rationale: string;
  targets_hypotheses: string[];
  expected_outcomes: { outcome: string; interpretation: "supports" | "contradicts" | "neutral"; hypothesis_id: string }[];
  cited_evidence: string[];
};

export type Pending = {
  case_id: string;
  round: number;
  proposals: Proposal[];
  conclude_option: { recommended: boolean; reason: string | null };
  final_round_of_suggestions: boolean;
};

export type JudgmentChange = {
  hypothesis_id: string;
  category: string;
  before: Support | null;
  after: Support | null;
  direction: "up" | "down" | "unchanged" | "new" | "removed";
  because: string[];
  rationale: string | null;
  round?: number;
};

export type Budget = { used: number; limit: number; remaining: number };

export type CaseStatus = "CREATED" | "RUNNING" | "AWAITING_APPROVAL" | "CONCLUDING" | "COMPLETED" | "FAILED_LLM" | "FAILED";

export type CaseDetail = {
  case_id: string;
  dataset_id: string;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
  error: string | null;
  last_event_seq: number;
  anomaly: AnomalyResult | null;
  evidence: Evidence[];
  timeline: { ts: string; source_system: string; description: string; evidence_id: string }[];
  hypotheses: Hypothesis[];
  pending: Pending | null;
  decisions: { action: string; proposal_id?: string | null; note?: string | null; actor?: string }[];
  verifications: { type: string; params: Record<string, unknown>; proposal_id: string; approval_id: string; actor: string; evidence_id: string; summary: string }[];
  judgment_changes: JudgmentChange[];
  conclusion: {
    category: string;
    support: string;
    label: string;
    statement: string | null;
    cited_evidence: string[];
    open_questions: string[];
    reason: string | null;
  } | null;
  budgets: { mcp_calls: Budget; llm_calls: Budget; verification_rounds: Budget; reject_all: Budget };
  llm_usage: { calls: number; tokens_in: number; tokens_out: number; cost_usd: number };
  report_available: boolean;
};

export type CaseSummary = { case_id: string; dataset_id: string; status: CaseStatus; created_at: string };

export type McpCall = {
  id: number;
  tool: string;
  arguments: string;
  status: string;
  error_code: string | null;
  duration_ms: number;
  mcp_call_id: string | null;
  result_size: number | null;
  created_at: string;
};

export type CaseEvent = { seq: number; type: string; payload: Record<string, unknown>; ts?: string };
