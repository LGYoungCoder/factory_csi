import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCase, useCases, useLlmStatus, useOverview, useStartCase } from "@/api/queries";
import { ApiError } from "@/api/client";
import { useCaseEvents } from "@/events/useCaseEvents";
import { ACTIVE_STATUSES } from "@/lib/status";
import { FactoryPanel } from "@/components/FactoryPanel";
import { LlmBanner, TopBar } from "@/components/TopBar";
import { AnomalyCard, EquipmentDrawer, EvidenceDrawer, EvidenceTimeline, ProgressStepper, StartButton, TrendCharts } from "@/components/Workspace";
import { ConclusionCard, DecisionPanel, EvidenceList, FailedCard, HypothesisCard, JudgmentChanges, McpCallList, StatusLine } from "@/components/Investigator";
import { Empty, Panel } from "@/components/ui";
import { useI18n } from "@/i18n";

export default function WorkspacePage() {
  const [params, setParams] = useSearchParams();
  const dataset = params.get("ds") ?? "ds-01";
  const caseId = params.get("case");
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    if (k === "ds") p.delete("case");
    setParams(p);
  };
  const llm = useLlmStatus();
  const { t } = useI18n();
  const llmOk = llm.data?.status === "OK";
  const overview = useOverview(dataset);
  const cases = useCases(dataset);
  const c = useCase(caseId);
  const live = useCaseEvents(caseId);
  const start = useStartCase(dataset);
  const [equip, setEquip] = useState<string | null>(null);
  const [ev, setEv] = useState<string | null>(null);

  // auto-select the newest case of the dataset when none selected
  useEffect(() => {
    if (!caseId && cases.data?.length) set("case", cases.data[0].case_id);
  }, [cases.data, caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeCase = (cases.data ?? []).some((x) => ACTIVE_STATUSES.includes(x.status));
  const startReason = !llmOk ? t("LLM unavailable – AI investigation is disabled")
    : !overview.data ? t("Dataset not available")
    : activeCase ? t("An investigation is already active on this dataset") : null;
  const detail = c.data && c.data.dataset_id === dataset ? c.data : null;
  const evidence = useMemo(() => detail?.evidence ?? [], [detail]);

  const onStart = () =>
    start.mutate(undefined, { onSuccess: (d) => set("case", d.case_id) });

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-200">
      <TopBar cases={cases.data ?? []} caseId={caseId} onCase={(id) => set("case", id)} />
      <LlmBanner />
      <div className="grid flex-1 grid-cols-[260px_minmax(0,1fr)_400px] gap-3 overflow-hidden p-3 xl:grid-cols-[280px_minmax(0,1fr)_440px]">
        <aside className="overflow-y-auto"><FactoryPanel dataset={dataset} onDataset={(d) => set("ds", d)} activeCase={activeCase} selected={equip} onSelect={setEquip} /></aside>

        <main className="flex min-w-0 flex-col gap-3 overflow-y-auto">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
            <StartButton disabledReason={startReason} onStart={onStart} pending={start.isPending} />
            {detail ? <ProgressStepper live={live} status={detail.status} /> : <span className="text-xs text-slate-500">{t("Select a scenario and press Start Investigation.")}</span>}
            {start.error && <span className="text-xs text-red-400">{(start.error as ApiError).message}</span>}
          </div>
          <AnomalyCard anomaly={detail?.anomaly ?? overview.data?.anomaly_detection} fromOverview={!detail?.anomaly} />
          <TrendCharts dataset={dataset} />
          <EvidenceTimeline items={detail?.timeline ?? []} evidence={evidence} highlight={equip} onOpen={setEv} />
        </main>

        <aside className="flex flex-col gap-3 overflow-y-auto" aria-label={t("AI Investigator")}>
          <Panel title={t("AI Investigator")}>
            {detail ? <StatusLine c={detail} live={live} /> : <Empty>{t("No investigation yet — select a scenario and press Start Investigation.")}</Empty>}
            {live.warnings.slice(-3).map((w, i) => <p key={i} className="mt-1 text-[11px] text-amber-400">⚠ {t(w.key)}: {w.detail}</p>)}
          </Panel>
          {detail && (
            <>
              <FailedCard c={detail} llmOk={llmOk} />
              <ConclusionCard c={detail} onOpen={setEv} />
              <DecisionPanel key={`${detail.case_id}-${detail.pending?.round ?? 0}`} c={detail} llmOk={llmOk} onOpen={setEv} />
              <JudgmentChanges c={detail} onOpen={setEv} />
              {detail.hypotheses.length > 0 && (
                <Panel title={`${t("Hypotheses")} (${detail.hypotheses.length})`}>
                  <div className="space-y-2">{detail.hypotheses.map((h) => <HypothesisCard key={h.hypothesis_id} h={h} onOpen={setEv} />)}</div>
                </Panel>
              )}
              <McpCallList caseId={detail.case_id} />
              <EvidenceList c={detail} onOpen={setEv} highlight={equip} />
            </>
          )}
        </aside>
      </div>
      <EquipmentDrawer dataset={dataset} equipmentId={equip} evidence={evidence} onClose={() => setEquip(null)} onOpenEvidence={setEv} />
      <EvidenceDrawer caseId={detail?.case_id ?? null} evidenceId={ev} evidence={evidence} onClose={() => setEv(null)} />
    </div>
  );
}
