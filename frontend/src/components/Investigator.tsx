import { useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp, CheckCircle2, FileText, RefreshCw, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { useDecision, useMcpCalls, useRetry } from "@/api/queries";
import type { CaseDetail, Hypothesis, McpCall, Proposal } from "@/api/types";
import { ApiError } from "@/api/client";
import type { LiveState } from "@/events/reducer";
import { CATEGORY_LABEL, VTYPE_LABEL, fmtMs, fmtUsd } from "@/lib/format";
import { SOURCE_STYLE, SUPPORT_LABEL, SUPPORT_STYLE } from "@/lib/status";
import { cn } from "@/lib/utils";
import { EvChip } from "./Workspace";
import { Badge, Button, Confirm, Empty, Panel, Tip } from "./ui";

export function StatusLine({ c, live }: { c: CaseDetail; live: LiveState }) {
  const b = c.budgets;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
      <span>Status <strong className="text-slate-100">{c.status}</strong></span>
      <span>Node <strong className="text-slate-200">{live.currentNode ?? "—"}</strong></span>
      <span>Round {b.verification_rounds.used}/{b.verification_rounds.limit}</span>
      <span>MCP calls {b.mcp_calls.used}/{b.mcp_calls.limit}</span>
      <span>LLM calls {b.llm_calls.used}/{b.llm_calls.limit}</span>
      <span>{c.llm_usage.tokens_in + c.llm_usage.tokens_out} tokens · {fmtUsd(c.llm_usage.cost_usd)}</span>
    </div>
  );
}

export function McpCallList({ caseId }: { caseId: string }) {
  const q = useMcpCalls(caseId);
  const [open, setOpen] = useState<number | null>(null);
  const calls = q.data ?? [];
  return (
    <Panel title={`MCP tool calls (${calls.length})`} right={<span className="text-[11px] text-slate-500">Industrial MCP Server · stdio</span>}>
      {!calls.length ? <Empty>No tool calls yet.</Empty> : (
        <ul className="max-h-60 space-y-1 overflow-y-auto pr-1">
          {calls.map((m: McpCall) => (
            <li key={m.id} className="rounded border border-slate-800 bg-slate-950/60">
              <button className="flex w-full items-center gap-2 px-2 py-1 text-left text-xs focus-visible:ring-2 focus-visible:ring-sky-400" onClick={() => setOpen(open === m.id ? null : m.id)} aria-expanded={open === m.id}>
                {m.status === "OK" ? <CheckCircle2 size={12} className="text-emerald-400" aria-label="ok" /> : <XCircle size={12} className="text-red-400" aria-label="error" />}
                <span className={cn("font-mono", m.tool === "run_simulated_verification" ? "text-emerald-300" : "text-sky-300")}>{m.tool}</span>
                <span className="truncate text-slate-500">{m.arguments.slice(0, 70)}</span>
                <span className="ml-auto shrink-0 text-slate-500">{fmtMs(m.duration_ms)}</span>
              </button>
              {open === m.id && (
                <div className="border-t border-slate-800 px-2 py-1 text-[11px] text-slate-400">
                  <div>call id <span className="font-mono text-slate-300">{m.mcp_call_id ?? "—"}</span> · status {m.status}{m.error_code ? ` (${m.error_code})` : ""} · result {m.result_size ?? 0} bytes</div>
                  <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-slate-300">{m.arguments}</pre>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function EvidenceList({ c, onOpen, highlight }: { c: CaseDetail; onOpen: (id: string) => void; highlight: string | null }) {
  const [filter, setFilter] = useState("ALL");
  const items = c.evidence.filter((e) => filter === "ALL" || e.source_system === filter);
  return (
    <Panel
      title={`Collected evidence (${c.evidence.length})`}
      right={
        <select aria-label="Filter by source system" className="rounded border border-slate-700 bg-slate-900 px-1 text-[11px]" value={filter} onChange={(e) => setFilter(e.target.value)}>
          {["ALL", "MES", "PPM", "EOL", "ANALYTICS", "VERIFICATION"].map((s) => <option key={s}>{s}</option>)}
        </select>
      }
    >
      {!items.length ? <Empty>No evidence yet.</Empty> : (
        <ul className="max-h-64 space-y-1 overflow-y-auto pr-1">
          {items.map((e) => (
            <li key={e.id} className={cn("flex items-start gap-2 rounded px-1 py-0.5 text-xs", highlight && e.equipment?.includes(highlight) && "bg-sky-500/10")}>
              <EvChip id={e.id} onOpen={onOpen} />
              <span className={cn("shrink-0 rounded px-1 text-[10px]", SOURCE_STYLE[e.source_system])}>{e.source_system}</span>
              <span className="text-slate-300">{e.title}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SupportBadge({ s }: { s: string }) {
  return <Badge className={SUPPORT_STYLE[s]}>Evidence support: {SUPPORT_LABEL[s] ?? s}</Badge>;
}

export function HypothesisCard({ h, onOpen }: { h: Hypothesis; onOpen: (id: string) => void }) {
  return (
    <article className="rounded border border-slate-800 bg-slate-950/60 p-2">
      <div className="flex flex-wrap items-center justify-between gap-1">
        <span className="text-xs font-semibold text-slate-300">{h.hypothesis_id} · {CATEGORY_LABEL[h.category] ?? h.category}</span>
        <SupportBadge s={h.support} />
      </div>
      <h3 className="mt-1 text-sm font-medium text-slate-100">{h.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-slate-300">{h.statement}</p>
      <div className="mt-2 space-y-1 text-[11px]">
        <div className="flex flex-wrap items-center gap-1"><span className="w-20 text-emerald-400">Supporting</span>{h.supporting_evidence.map((e) => <EvChip key={e} id={e} onOpen={onOpen} />)}{!h.supporting_evidence.length && <span className="text-slate-500">none</span>}</div>
        <div className="flex flex-wrap items-center gap-1"><span className="w-20 text-red-400">Contradicting</span>{h.contradicting_evidence.map((e) => <EvChip key={e} id={e} onOpen={onOpen} />)}{!h.contradicting_evidence.length && <span className="text-slate-500">none</span>}</div>
        {h.missing_evidence.length > 0 && (
          <div><span className="text-amber-400">Missing evidence</span><ul className="ml-4 list-disc text-slate-400">{h.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
        )}
      </div>
    </article>
  );
}

function ProposalCard({ p, hyps, onApprove, disabledReason, onOpen }: { p: Proposal; hyps: Hypothesis[]; onApprove: () => void; disabledReason: string | null; onOpen: (id: string) => void }) {
  const hname = (id: string) => hyps.find((h) => h.hypothesis_id === id)?.category ?? id;
  const params = Object.entries(p.params).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");
  return (
    <article className="rounded border border-sky-500/40 bg-sky-500/5 p-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-sky-200">#{p.rank} {VTYPE_LABEL[p.verification_type]}</span>
        <Badge className="border-emerald-500/40 text-emerald-300">simulated</Badge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-slate-300">{params}</p>
      <p className="mt-1 text-xs text-slate-300">{p.rationale}</p>
      {p.expected_outcomes.length > 0 && (
        <table className="mt-2 w-full text-[11px]">
          <thead><tr className="text-slate-500"><th className="text-left">If outcome</th><th className="text-left">→</th><th className="text-left">Hypothesis</th></tr></thead>
          <tbody>
            {p.expected_outcomes.map((o, i) => (
              <tr key={i} className="border-t border-slate-800">
                <td className="py-0.5 pr-2 text-slate-300">{o.outcome}</td>
                <td className={cn("pr-2", o.interpretation === "supports" ? "text-emerald-400" : o.interpretation === "contradicts" ? "text-red-400" : "text-slate-400")}>{o.interpretation}</td>
                <td className="text-slate-400">{o.hypothesis_id} {CATEGORY_LABEL[hname(o.hypothesis_id)] ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex flex-wrap gap-1">{p.cited_evidence.map((e) => <EvChip key={e} id={e} onOpen={onOpen} />)}</div>
        <Tip content={disabledReason}>
          <Button variant="success" onClick={onApprove} disabled={!!disabledReason}>Approve Verification</Button>
        </Tip>
      </div>
    </article>
  );
}

export function DecisionPanel({ c, llmOk, onOpen }: { c: CaseDetail; llmOk: boolean; onOpen: (id: string) => void }) {
  const decide = useDecision(c.case_id);
  const [showAll, setShowAll] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [note, setNote] = useState("");
  const [conclude, setConclude] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const pending = c.pending;
  if (c.status !== "AWAITING_APPROVAL" || !pending) return null;
  const busy = submitted || decide.isPending;
  const rejectsLeft = c.budgets.reject_all.remaining;
  const baseReason = !llmOk ? "LLM unavailable – AI investigation is disabled" : busy ? "Decision submitted" : null;
  const props = showAll ? pending.proposals : pending.proposals.slice(0, 1);
  const send = (body: { action: string; proposal_id?: string; note?: string }) => {
    setSubmitted(true);
    decide.mutate(body, { onError: () => setSubmitted(false) });
  };
  return (
    <Panel title="Next Best Verification" right={pending.final_round_of_suggestions ? <Badge className="border-amber-500/50 text-amber-300">final round of suggestions</Badge> : <span className="text-[11px] text-slate-500">proposal round {pending.round}</span>}>
      <div className="space-y-2">
        {pending.proposals.length === 0 && <p className="text-sm text-slate-300">No valid verification proposal. {pending.conclude_option.reason}</p>}
        {pending.conclude_option.recommended && pending.proposals.length > 0 && pending.conclude_option.reason && (
          <p className="text-xs text-amber-300">AI suggests concluding: {pending.conclude_option.reason}</p>
        )}
        {props.map((p) => (
          <ProposalCard key={p.proposal_id} p={p} hyps={c.hypotheses} onOpen={onOpen} disabledReason={baseReason}
            onApprove={() => send({ action: "approve", proposal_id: p.proposal_id, ...(note.trim() ? { note: note.trim() } : {}) })} />
        ))}
        <div className="flex flex-wrap gap-2">
          {pending.proposals.length > 1 && (
            <Button variant="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show top suggestion only" : `Show other suggestions (${pending.proposals.length - 1})`}</Button>
          )}
          <Tip content={rejectsLeft <= 0 ? "Reject limit reached (2 per case)" : baseReason}>
            <Button onClick={() => setRejectOpen(!rejectOpen)} disabled={!!baseReason || rejectsLeft <= 0 || pending.proposals.length === 0}>Reject all ({rejectsLeft} left)</Button>
          </Tip>
          <Tip content={baseReason}>
            <Button variant="secondary" onClick={() => setConclude(true)} disabled={!!baseReason}>Conclude Investigation</Button>
          </Tip>
        </div>
        {rejectOpen && (
          <div className="rounded border border-slate-700 p-2">
            <label className="text-xs text-slate-400" htmlFor="reject-note">Reason for rejecting all suggestions (required, ≤500 characters)</label>
            <textarea id="reject-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 h-16 w-full rounded border border-slate-700 bg-slate-950 p-1 text-sm" />
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
              <span>{note.length}/500</span>
              <Button variant="danger" disabled={!note.trim() || busy} onClick={() => send({ action: "reject_all", note: note.trim() })}>Reject all suggestions</Button>
            </div>
          </div>
        )}
        {decide.error && <p className="text-xs text-red-400">{(decide.error as ApiError).message}</p>}
        <Confirm open={conclude} onOpenChange={setConclude} variant="primary" title="Conclude the investigation?"
          body="No further verification will run. The AI writes the final conclusion and the report from the current evidence."
          confirmLabel="Conclude" onConfirm={() => send({ action: "conclude" })} />
      </div>
    </Panel>
  );
}

export function JudgmentChanges({ c, onOpen }: { c: CaseDetail; onOpen: (id: string) => void }) {
  if (!c.judgment_changes.length) return null;
  return (
    <Panel title="Judgment changes">
      <ul className="space-y-1">
        {c.judgment_changes.map((j, i) => (
          <li key={i} className="rounded border border-slate-800 p-1.5 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-500">round {j.round}</span>
              <span className="font-medium text-slate-200">{j.hypothesis_id} {CATEGORY_LABEL[j.category] ?? j.category}</span>
              <span className="text-slate-400">{j.before ? SUPPORT_LABEL[j.before] : "—"}</span>
              {j.direction === "up" ? <ArrowUp size={12} className="text-emerald-400" aria-label="up" /> : j.direction === "down" ? <ArrowDown size={12} className="text-red-400" aria-label="down" /> : <ArrowRight size={12} className="text-slate-400" aria-label={j.direction} />}
              <span className="font-semibold text-slate-100">{j.after ? SUPPORT_LABEL[j.after] : "removed"}</span>
              {j.because.length > 0 && <span className="text-slate-500">because</span>}
              {j.because.map((e) => <EvChip key={e} id={e} onOpen={onOpen} />)}
            </div>
            {j.rationale && <p className="mt-1 text-slate-400">{j.rationale}</p>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function ConclusionCard({ c, onOpen }: { c: CaseDetail; onOpen: (id: string) => void }) {
  if (!c.conclusion) return null;
  const k = c.conclusion;
  return (
    <Panel title="Conclusion" right={c.report_available ? <Link to={`/cases/${c.case_id}/report`} className="flex items-center gap-1 text-xs text-sky-300 hover:underline"><FileText size={12} /> Open report</Link> : null}>
      <div className="text-sm font-semibold text-slate-100">{k.label}: {CATEGORY_LABEL[k.category] ?? k.category}</div>
      <div className="mt-1"><SupportBadge s={k.support} /></div>
      {k.statement && <p className="mt-2 text-xs leading-relaxed text-slate-300">{k.statement}</p>}
      <div className="mt-2 flex flex-wrap gap-1">{k.cited_evidence.slice(0, 12).map((e) => <EvChip key={e} id={e} onOpen={onOpen} />)}</div>
      <p className="mt-2 text-[11px] text-slate-500">Simulated data · decision support · not a certified root cause.</p>
    </Panel>
  );
}

export function FailedCard({ c, llmOk }: { c: CaseDetail; llmOk: boolean }) {
  const retry = useRetry(c.case_id);
  if (c.status !== "FAILED_LLM" && c.status !== "FAILED") return null;
  return (
    <div role="alert" className="rounded border border-red-700 bg-red-950/50 p-3 text-sm text-red-200">
      <div className="font-semibold">{c.status === "FAILED_LLM" ? "Investigation paused: LLM failure" : "Investigation failed"}</div>
      <p className="mt-1 text-xs text-red-300">{c.error}</p>
      {c.status === "FAILED_LLM" && (
        <Tip content={!llmOk ? "LLM unavailable – retry is disabled" : null}>
          <Button className="mt-2" onClick={() => retry.mutate()} disabled={!llmOk || retry.isPending}><RefreshCw size={12} /> Retry from last checkpoint</Button>
        </Tip>
      )}
      {retry.error && <p className="mt-1 text-xs text-red-300">{(retry.error as ApiError).message}</p>}
    </div>
  );
}
