/* eslint-disable @typescript-eslint/no-explicit-any -- equipment detail payload differs per equipment type */
import { useMemo, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { Play } from "lucide-react";
import type { EChartsOption } from "echarts";
import { useEquipment, useEvidenceDetail, useTrends } from "@/api/queries";
import type { AnomalyResult, CaseDetail, Evidence } from "@/api/types";
import { STEPS, type LiveState } from "@/events/reducer";
import { fmtP, fmtRate, fmtTime, fmtTs } from "@/lib/format";
import { SOURCE_STYLE, relatesTo, statusStyle } from "@/lib/status";
import { cn } from "@/lib/utils";
import { EChart } from "./EChart";
import { Badge, Button, Drawer, Empty, Panel, Skeleton, Tip } from "./ui";

export function AnomalyCard({ anomaly, fromOverview }: { anomaly: AnomalyResult | null | undefined; fromOverview: boolean }) {
  if (!anomaly) return <Panel title="Anomaly"><Skeleton className="h-16" /></Panel>;
  return (
    <Panel
      title="Anomaly"
      right={fromOverview ? <span className="text-[11px] text-slate-500">Statistical detection (no investigation yet)</span> : null}
    >
      {anomaly.status !== "ANOMALY" ? (
        <p className="text-sm text-slate-300">No anomaly detected in this dataset (last 3 h vs first 2 h).</p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {anomaly.anomalies.map((a) => (
            <div key={a.equipment_id} className="rounded border border-red-500/40 bg-red-500/5 p-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-red-300">■ {a.equipment_id} FAIL_Rate elevated</span>
                <span className="text-xs text-slate-400">p = {fmtP(a.p_value)}</span>
              </div>
              <div className="mt-1 text-sm text-slate-200">
                {fmtRate(a.baseline_rate)} <span className="text-slate-500">({a.baseline_counts[0]}/{a.baseline_counts[1]})</span>
                <span className="mx-2 text-slate-500">→</span>
                <strong>{fmtRate(a.window_rate)}</strong> <span className="text-slate-500">({a.window_counts[0]}/{a.window_counts[1]})</span>
              </div>
              <div className="text-[11px] text-slate-500">
                baseline {fmtTime(anomaly.baseline_window.start)}–{fmtTime(anomaly.baseline_window.end)} · window{" "}
                {fmtTime(anomaly.detected_window.start)}–{fmtTime(anomaly.detected_window.end)} UTC
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

const TESTER_STYLE: Record<string, { color: string; dash: "solid" | "dashed" }> = {
  "EOL-A": { color: "#38bdf8", dash: "solid" },
  "EOL-B": { color: "#f472b6", dash: "dashed" },
};

export function TrendCharts({ dataset }: { dataset: string }) {
  const [bucket, setBucket] = useState(30);
  const t = useTrends(dataset, bucket);
  const opts = useMemo(() => {
    if (!t.data) return null;
    const marks = t.data.process_changes.map((c) => ({
      xAxis: c.ts, label: { formatter: `${c.equipment_id} ${c.old_value}→${c.new_value}`, color: "#fbbf24", fontSize: 10 },
    }));
    const markLine = marks.length ? { symbol: "none", lineStyle: { color: "#fbbf24", type: "dotted" as const }, data: marks } : undefined;
    const base: EChartsOption = {
      grid: { left: 48, right: 16, top: 28, bottom: 28 },
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { color: "#94a3b8", fontSize: 11 } },
      xAxis: { type: "time", axisLabel: { color: "#94a3b8", formatter: (v: number) => new Date(v).toISOString().slice(11, 16) } },
    };
    const fail: EChartsOption = {
      ...base,
      yAxis: { type: "value", axisLabel: { color: "#94a3b8", formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      series: ["EOL-A", "EOL-B"].map((tid, i) => ({
        name: tid, type: "line", showSymbol: true, symbol: i ? "triangle" : "circle",
        lineStyle: { color: TESTER_STYLE[tid].color, type: TESTER_STYLE[tid].dash }, itemStyle: { color: TESTER_STYLE[tid].color },
        data: t.data!.fail_rate.filter((b) => b.tester_id === tid).map((b) => [b.bucket_start, b.fail_rate]),
        markLine: i === 0 ? markLine : undefined,
      })),
    };
    const versions = [...new Set(t.data.st20.map((s) => s.program_version))];
    const st20: EChartsOption = {
      ...base,
      yAxis: { type: "value", name: "angle °", scale: true, axisLabel: { color: "#94a3b8" } },
      series: versions.map((v, i) => ({
        name: `angle mean ${v}`, type: "line", showSymbol: true, lineStyle: { type: i ? "dashed" : "solid" },
        data: t.data!.st20.filter((s) => s.parameter === "angle" && s.program_version === v).map((s) => [s.bucket_start, s.mean]),
        markLine: i === 0 ? markLine : undefined,
      })),
    };
    const ref: EChartsOption = {
      ...base,
      yAxis: { type: "value", name: "deviation V", axisLabel: { color: "#94a3b8" } },
      series: ["EOL-A", "EOL-B"].map((tid, i) => ({
        name: tid, type: "line", symbol: i ? "triangle" : "circle", symbolSize: 8,
        lineStyle: { color: TESTER_STYLE[tid].color, type: TESTER_STYLE[tid].dash }, itemStyle: { color: TESTER_STYLE[tid].color },
        data: t.data!.reference_deviations[tid].map((c) => [c.ts, c.deviation]),
        markLine: i === 0 ? { symbol: "none", lineStyle: { color: "#ef4444", type: "dotted" as const }, data: [{ yAxis: 0.15 }, { yAxis: -0.15 }] } : undefined,
      })),
    };
    return { fail, st20, ref };
  }, [t.data]);
  return (
    <Panel
      title="Trends"
      right={
        <label className="text-[11px] text-slate-400">
          bucket{" "}
          <select aria-label="Bucket size" value={bucket} onChange={(e) => setBucket(Number(e.target.value))} className="rounded border border-slate-700 bg-slate-900 px-1 text-xs">
            {[15, 30, 60, 120].map((b) => <option key={b} value={b}>{b} min</option>)}
          </select>
        </label>
      }
    >
      {!opts ? <Skeleton className="h-56" /> : (
        <Tabs.Root defaultValue="fail">
          <Tabs.List className="mb-2 flex gap-1 text-xs" aria-label="Trend charts">
            {[["fail", "FAIL_Rate by tester"], ["st20", "ST-20 tightening angle"], ["ref", "Reference deviation"]].map(([v, l]) => (
              <Tabs.Trigger key={v} value={v} className="rounded px-2 py-1 text-slate-400 data-[state=active]:bg-slate-800 data-[state=active]:text-slate-100">{l}</Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="fail"><EChart option={opts.fail} /></Tabs.Content>
          <Tabs.Content value="st20"><EChart option={opts.st20} /></Tabs.Content>
          <Tabs.Content value="ref"><EChart option={opts.ref} /></Tabs.Content>
        </Tabs.Root>
      )}
    </Panel>
  );
}

export function EvChip({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button onClick={() => onOpen(id)} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-sky-300 hover:bg-slate-700 focus-visible:ring-2 focus-visible:ring-sky-400">
      {id}
    </button>
  );
}

export function EvidenceTimeline({ items, evidence, highlight, onOpen }: {
  items: CaseDetail["timeline"]; evidence: Evidence[]; highlight: string | null; onOpen: (id: string) => void;
}) {
  const byId = Object.fromEntries(evidence.map((e) => [e.id, e]));
  const rows = [...items];
  for (const e of evidence) if (e.ts && !rows.some((r) => r.evidence_id === e.id)) rows.push({ ts: e.ts, source_system: e.source_system, description: e.title, evidence_id: e.id });
  rows.sort((a, b) => a.ts.localeCompare(b.ts));
  return (
    <Panel title="Evidence timeline">
      {!rows.length ? <Empty>No timeline yet — events appear as evidence is collected.</Empty> : (
        <ol className="relative ml-2 border-l border-slate-700">
          {rows.map((r) => {
            const hl = highlight && byId[r.evidence_id] && relatesTo(byId[r.evidence_id], highlight);
            return (
              <li key={r.evidence_id} className={cn("mb-2 ml-4", hl && "rounded bg-sky-500/10")}>
                <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-slate-900 bg-slate-500" aria-hidden />
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-slate-400">{fmtTs(r.ts).slice(11)}</span>
                  <span className={cn("rounded px-1.5 text-[11px]", SOURCE_STYLE[r.source_system])}>{r.source_system}</span>
                  <span className="text-slate-200">{r.description}</span>
                  <EvChip id={r.evidence_id} onOpen={onOpen} />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

export function ProgressStepper({ live, status }: { live: LiveState; status: string | undefined }) {
  const done = status === "COMPLETED";
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="Investigation progress">
      {STEPS.map((s, i) => {
        const state = done || i < live.currentStep ? "done" : i === live.currentStep ? "active" : i <= live.maxStep ? "done" : "todo";
        return (
          <li key={s} className={cn("rounded px-2 py-0.5",
            state === "done" && "bg-emerald-500/15 text-emerald-300",
            state === "active" && "bg-sky-500/20 text-sky-200 ring-1 ring-sky-500/60",
            state === "todo" && "bg-slate-800 text-slate-500")}
            aria-current={state === "active" ? "step" : undefined}>
            {i + 1}. {s}
          </li>
        );
      })}
    </ol>
  );
}

export function StartButton({ disabledReason, onStart, pending }: { disabledReason: string | null; onStart: () => void; pending: boolean }) {
  return (
    <Tip content={disabledReason}>
      <Button variant="primary" onClick={onStart} disabled={!!disabledReason || pending} className="px-4">
        <Play size={14} /> {pending ? "Starting…" : "Start Investigation"}
      </Button>
    </Tip>
  );
}

export function EvidenceDrawer({ caseId, evidenceId, evidence, onClose }: { caseId: string | null; evidenceId: string | null; evidence: Evidence[]; onClose: () => void }) {
  const d = useEvidenceDetail(caseId, evidenceId);
  const ev = evidence.find((e) => e.id === evidenceId);
  return (
    <Drawer open={!!evidenceId} onOpenChange={(o) => !o && onClose()} title={`${evidenceId ?? ""} · ${ev?.title ?? ""}`}>
      {ev && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <Badge className="border-slate-600 text-slate-300">{ev.kind}</Badge>
            <span className={cn("rounded px-1.5 text-[11px]", SOURCE_STYLE[ev.source_system])}>{ev.source_system}</span>
            {ev.kind === "verification" && <Badge className="border-emerald-500/50 text-emerald-300">simulation</Badge>}
          </div>
          <p className="text-slate-200">{ev.summary}</p>
          <details>
            <summary className="cursor-pointer text-xs text-slate-400">Computed data</summary>
            <pre className="mt-1 max-h-64 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-300">{JSON.stringify({ ...ev.data, ref_rows: undefined }, null, 1)}</pre>
          </details>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Source records ({ev.record_refs.length})</h3>
          {d.isLoading && <Skeleton className="h-24" />}
          {d.data?.source_records_error && <p className="text-xs text-red-400">{d.data.source_records_error}</p>}
          {d.data?.source_records.length === 0 && <Empty>This evidence item has no source record references.</Empty>}
          <div className="space-y-2">
            {d.data?.source_records.map((r) => (
              <div key={r.ref} className="rounded border border-slate-800">
                <div className="border-b border-slate-800 px-2 py-1 font-mono text-[11px] text-sky-300">{r.ref}</div>
                <table className="w-full text-[11px]">
                  <tbody>
                    {Object.entries(r.record).map(([k, v]) => (
                      <tr key={k} className="border-b border-slate-900"><td className="w-40 px-2 py-0.5 text-slate-500">{k}</td><td className="px-2 py-0.5 font-mono text-slate-200">{String(v)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>
      )}
    </Drawer>
  );
}

export function EquipmentDrawer({ dataset, equipmentId, evidence, onClose, onOpenEvidence }: {
  dataset: string; equipmentId: string | null; evidence: Evidence[]; onClose: () => void; onOpenEvidence: (id: string) => void;
}) {
  const q = useEquipment(dataset, equipmentId);
  const d = q.data as Record<string, any> | undefined;
  const related = equipmentId ? evidence.filter((e) => relatesTo(e, equipmentId)) : [];
  const s = statusStyle(d?.status);
  return (
    <Drawer open={!!equipmentId} onOpenChange={(o) => !o && onClose()} title={`${equipmentId ?? ""} · ${d?.name ?? ""}`}>
      {q.isLoading || !d ? <Skeleton className="h-40" /> : (
        <div className="space-y-4">
          <div className={cn("text-sm font-semibold", s.text)}>{s.icon} {s.label}</div>
          {d.reasons?.length > 0 && <ul className="list-disc pl-5 text-xs text-slate-300">{d.reasons.map((r: any) => <li key={r.code}>{r.message}</li>)}</ul>}
          {d.totals && (
            <div className="grid grid-cols-3 gap-2 text-xs">
              <Stat label="First tests" value={d.totals.test_count} />
              <Stat label="Fails" value={d.totals.fail_count} />
              <Stat label="FAIL_Rate" value={fmtRate(d.totals.fail_rate)} />
              {d.by_model?.map((m: any) => <Stat key={m.model_id} label={m.model_id} value={`${fmtRate(m.fail_rate)} (${m.fail_count}/${m.test_count})`} />)}
            </div>
          )}
          {d.fail_rate_buckets && (
            <EChart height={160} option={{
              grid: { left: 40, right: 8, top: 10, bottom: 24 }, tooltip: { trigger: "axis" },
              xAxis: { type: "time", axisLabel: { color: "#94a3b8", formatter: (v: number) => new Date(v).toISOString().slice(11, 16) } },
              yAxis: { type: "value", axisLabel: { color: "#94a3b8", formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
              series: [{ type: "bar", data: d.fail_rate_buckets.map((b: any) => [b.bucket_start, b.fail_rate]), itemStyle: { color: "#f472b6" } }],
            }} />
          )}
          {d.reference_checks && (
            <Table title="Reference sample checks" cols={["ts", "deviation", "result", "origin"]} rows={d.reference_checks} />
          )}
          {d.recent_failures && <Table title="Recent failures" cols={["ts", "sn", "model_id", "test_id"]} rows={d.recent_failures} />}
          {d.process_changes && <Table title="Process changes" cols={["ts", "change_type", "old_value", "new_value", "changed_by"]} rows={d.process_changes} />}
          {d.step_total_count !== undefined && d.step_total_count !== null && <p className="text-xs text-slate-400">Process steps in data range: {d.step_total_count}</p>}
          <Table title="Equipment events" cols={["ts", "event_type", "severity", "details_json"]} rows={d.events ?? []} />
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Related evidence in this case</h3>
            {related.length ? <div className="flex flex-wrap gap-1">{related.map((e) => <EvChip key={e.id} id={e.id} onOpen={onOpenEvidence} />)}</div> : <Empty>No related evidence (start an investigation first).</Empty>}
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded border border-slate-800 p-2"><div className="text-slate-500">{label}</div><div className="text-slate-100">{value}</div></div>;
}

function Table({ title, cols, rows }: { title: string; cols: string[]; rows: Record<string, unknown>[] }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">{title} ({rows.length})</h3>
      {rows.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
        <div className="max-h-48 overflow-auto rounded border border-slate-800">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-slate-900"><tr>{cols.map((c) => <th key={c} className="px-2 py-1 text-left text-slate-500">{c}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-slate-900">{cols.map((c) => <td key={c} className="px-2 py-0.5 font-mono text-slate-300">{c === "ts" ? fmtTs(String(r[c])).slice(11) : String(r[c] ?? "—")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
