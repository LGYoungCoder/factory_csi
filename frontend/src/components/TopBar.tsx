import { Activity, RefreshCw } from "lucide-react";
import { useLlmStatus, useRefreshLlm } from "@/api/queries";
import type { CaseSummary } from "@/api/types";
import { Badge, Tip } from "./ui";
import { cn } from "@/lib/utils";

const LLM_STYLE = {
  OK: "border-emerald-500/50 text-emerald-300",
  UNAVAILABLE: "border-red-500/60 text-red-300",
  MISCONFIGURED: "border-amber-500/60 text-amber-300",
} as const;

export function TopBar({ cases, caseId, onCase }: { cases: CaseSummary[]; caseId: string | null; onCase: (id: string | null) => void }) {
  const llm = useLlmStatus();
  const refresh = useRefreshLlm();
  const st = llm.data?.status ?? "UNAVAILABLE";
  return (
    <header className="flex items-center gap-4 border-b border-slate-800 bg-slate-950 px-4 py-2">
      <div className="flex items-center gap-2">
        <Activity className="text-sky-400" size={20} aria-hidden />
        <span className="text-base font-semibold tracking-tight text-slate-100">Factory CSI</span>
        <span className="hidden text-xs text-slate-500 lg:inline">AI Manufacturing Quality Investigation Copilot</span>
      </div>
      <span className="text-sm text-slate-400">Factory Alpha · Line A</span>
      <Badge className="border-sky-500/50 bg-sky-500/10 text-sky-300">SIMULATION</Badge>
      <div className="ml-auto flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-slate-400">
          Case
          <select
            aria-label="Investigation case"
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
            value={caseId ?? ""}
            onChange={(e) => onCase(e.target.value || null)}
          >
            <option value="">— none —</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} · {c.status}
              </option>
            ))}
          </select>
        </label>
        <Tip content={llm.data?.reason ?? (st === "OK" ? `Connected · checked ${llm.data?.checked_at ?? ""}` : "")}>
          <button
            onClick={() => refresh.mutate()}
            aria-label="Refresh LLM status"
            className={cn("flex items-center gap-1.5 rounded border px-2 py-1 text-xs focus-visible:ring-2 focus-visible:ring-sky-400", LLM_STYLE[st])}
          >
            <span aria-hidden>{st === "OK" ? "●" : "▲"}</span>
            LLM {st === "OK" ? "connected" : st.toLowerCase()} · {llm.data?.model ?? "…"}
            <RefreshCw size={12} className={refresh.isPending ? "animate-spin motion-reduce:animate-none" : ""} />
          </button>
        </Tip>
      </div>
    </header>
  );
}

export function LlmBanner() {
  const llm = useLlmStatus();
  if (!llm.data || llm.data.status === "OK") return null;
  return (
    <div role="alert" className="border-b border-red-800 bg-red-950/70 px-4 py-2 text-sm text-red-200">
      <strong>LLM unavailable – AI investigation is disabled.</strong> Overview and statistics remain available.
      {llm.data.reason ? <span className="ml-2 text-red-300/80">({llm.data.reason})</span> : null}
    </div>
  );
}
