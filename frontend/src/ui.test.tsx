import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { initialLive, liveReducer } from "@/events/reducer";
import { fmtP, fmtRate, fmtTs } from "@/lib/format";
import { STATUS_STYLE, relatesTo, statusStyle } from "@/lib/status";
import { DecisionPanel } from "@/components/Investigator";
import { StartButton } from "@/components/Workspace";
import type { CaseDetail } from "@/api/types";

const ev = (seq: number, type: string, payload: Record<string, unknown> = {}) => ({ type: "event" as const, event: { seq, type, payload } });

describe("live event reducer", () => {
  it("orders, dedupes and tracks progress", () => {
    let s = liveReducer(initialLive, ev(1, "status_changed", { from: "CREATED", to: "RUNNING" }));
    s = liveReducer(s, ev(2, "node_started", { node: "detect_anomaly" }));
    s = liveReducer(s, ev(2, "node_started", { node: "collect_evidence" })); // duplicate seq ignored
    expect(s.currentStep).toBe(1);
    expect(s.events).toHaveLength(2);
    s = liveReducer(s, ev(3, "awaiting_approval", {}));
    expect(s.currentStep).toBe(6);
    s = liveReducer(s, ev(4, "citation_dropped", { item: "x", invalid_ids: ["EV-999"] }));
    expect(s.warnings[0].detail).toContain("EV-999");
    s = liveReducer(s, ev(5, "audit", { name: "tool_call_rejected" }));
    expect(s.audit).toHaveLength(1);
    s = liveReducer(s, ev(6, "something_new", {})); // unknown type ignored without error
    expect(s.lastSeq).toBe(6);
    s = liveReducer(s, ev(7, "completed", { final_status: "COMPLETED" }));
    expect(s.finished).toBe(true);
    expect(s.status).toBe("COMPLETED");
  });
});

describe("formatting and status mapping", () => {
  it("formats numbers and times", () => {
    expect(fmtRate(0.1712)).toBe("17.1%");
    expect(fmtRate(null)).toBe("—");
    expect(fmtP(0.0000238)).toBe("2.4e-5");
    expect(fmtP(0.5)).toBe("0.500");
    expect(fmtTs("2026-11-02T10:08:00Z")).toBe("2026-11-02 10:08:00 UTC");
  });
  it("maps status to colour and a text label", () => {
    expect(statusStyle("RED").label).toBe("Anomaly");
    expect(statusStyle("bogus")).toBe(STATUS_STYLE.GREY);
    expect(Object.values(STATUS_STYLE).every((s) => s.label && s.icon)).toBe(true);
  });
  it("finds evidence related to equipment", () => {
    expect(relatesTo({ equipment: ["EOL-B"], record_refs: [], data: {} }, "EOL-B")).toBe(true);
    expect(relatesTo({ record_refs: [], data: { tester_id: "EOL-A" } }, "EOL-B")).toBe(false);
  });
});

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <Tooltip.Provider><MemoryRouter>{ui}</MemoryRouter></Tooltip.Provider>
    </QueryClientProvider>,
  );
}

const caseFixture = (): CaseDetail => ({
  case_id: "CASE-0001", dataset_id: "ds-01", status: "AWAITING_APPROVAL", created_at: "", updated_at: "", error: null, last_event_seq: 5,
  anomaly: null, evidence: [], timeline: [], hypotheses: [], decisions: [], verifications: [], judgment_changes: [], conclusion: null,
  pending: {
    case_id: "CASE-0001", round: 1, final_round_of_suggestions: false, conclude_option: { recommended: false, reason: null },
    proposals: [{ proposal_id: "P-1-1", rank: 1, verification_type: "cross_retest", params: { serial_numbers: ["SN-2600001"], target_tester_id: "EOL-A" },
      rationale: "Discriminates tester vs product", targets_hypotheses: ["H-1"], expected_outcomes: [], cited_evidence: ["EV-001"] }],
  },
  budgets: { mcp_calls: { used: 1, limit: 20, remaining: 19 }, llm_calls: { used: 1, limit: 40, remaining: 39 },
    verification_rounds: { used: 0, limit: 3, remaining: 3 }, reject_all: { used: 0, limit: 2, remaining: 2 } },
  llm_usage: { calls: 1, tokens_in: 1, tokens_out: 1, cost_usd: 0 }, report_available: false,
});

describe("decision panel", () => {
  it("requires a reason before rejecting all", async () => {
    wrap(<DecisionPanel c={caseFixture()} llmOk onOpen={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Reject all \(2 left\)/ }));
    const submit = screen.getByRole("button", { name: "Reject all suggestions" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Reason for rejecting/), "check the reference sample first");
    expect(submit).toBeEnabled();
  });
  it("disables every action when the LLM is unavailable", () => {
    wrap(<DecisionPanel c={caseFixture()} llmOk={false} onOpen={() => {}} />);
    expect(screen.getByRole("button", { name: "Approve Verification" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Conclude Investigation" })).toBeDisabled();
  });
  it("disables Start Investigation with a reason", () => {
    wrap(<StartButton disabledReason="LLM unavailable – AI investigation is disabled" onStart={() => {}} pending={false} />);
    expect(screen.getByRole("button", { name: /Start Investigation/ })).toBeDisabled();
  });
});
