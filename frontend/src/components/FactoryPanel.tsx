import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { useOverview, useResetDataset, useScenarios } from "@/api/queries";
import type { EquipmentStatus } from "@/api/types";
import { fmtRate, fmtTs } from "@/lib/format";
import { statusStyle } from "@/lib/status";
import { Button, Confirm, Panel, Skeleton, Tip } from "./ui";
import { ApiError } from "@/api/client";

const NODES: { id: string; label: string; sub: string; x: number; y: number }[] = [
  { id: "ST-10", label: "ST-10", sub: "Component assembly", x: 10, y: 20 },
  { id: "ST-20", label: "ST-20", sub: "Bolt tightening", x: 10, y: 110 },
  { id: "ST-30", label: "ST-30", sub: "Functional assembly", x: 10, y: 200 },
  { id: "EOL-A", label: "EOL-A", sub: "EOL tester A", x: 10, y: 300 },
  { id: "EOL-B", label: "EOL-B", sub: "EOL tester B", x: 140, y: 300 },
];

export function LineTopology({ statuses, rates, selected, onSelect }: {
  statuses: EquipmentStatus[]; rates?: Record<string, { last_60_min: number | null }>; selected: string | null; onSelect: (id: string) => void;
}) {
  const get = (id: string) => statuses.find((s) => s.equipment_id === id);
  return (
    <svg viewBox="0 0 260 370" className="w-full" role="group" aria-label="Line A topology">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#475569" />
        </marker>
      </defs>
      {[[70, 70, 70, 108], [70, 160, 70, 198], [70, 250, 70, 298], [70, 270, 200, 270], [200, 270, 200, 298]].map(([x1, y1, x2, y2], i) => (
        <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#475569" strokeWidth={2} markerEnd={i === 3 ? undefined : "url(#arrow)"} />
      ))}
      {NODES.map((n) => {
        const st = get(n.id);
        const s = statusStyle(st?.status);
        const rate = rates?.[n.id]?.last_60_min;
        return (
          <g
            key={n.id}
            role="button"
            tabIndex={0}
            aria-label={`${n.label} ${n.sub}: ${s.label}`}
            onClick={() => onSelect(n.id)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(n.id)}
            className="cursor-pointer focus:outline-none"
          >
            <rect x={n.x} y={n.y} width={120} height={50} rx={6} fill={s.fill} stroke={selected === n.id ? "#38bdf8" : s.stroke} strokeWidth={selected === n.id ? 3 : 1.5} />
            <text x={n.x + 10} y={n.y + 20} fill="#e2e8f0" fontSize={13} fontWeight={600}>{n.label}</text>
            <text x={n.x + 110} y={n.y + 20} fill={s.stroke} fontSize={11} textAnchor="end">{s.icon} {s.label}</text>
            <text x={n.x + 10} y={n.y + 38} fill="#94a3b8" fontSize={10}>{n.sub}{rate !== undefined ? ` · ${fmtRate(rate)}` : ""}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function FactoryPanel({ dataset, onDataset, activeCase, selected, onSelect }: {
  dataset: string; onDataset: (d: string) => void; activeCase: boolean; selected: string | null; onSelect: (id: string) => void;
}) {
  const sc = useScenarios();
  const ov = useOverview(dataset);
  const reset = useResetDataset(dataset);
  const [confirm, setConfirm] = useState(false);
  const current = sc.data?.find((s) => s.dataset_id === dataset);
  return (
    <div className="flex flex-col gap-3">
      <Panel title="Scenario">
        <select
          aria-label="Scenario"
          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100"
          value={dataset}
          onChange={(e) => onDataset(e.target.value)}
        >
          {sc.data?.map((s) => (
            <option key={s.dataset_id} value={s.dataset_id} disabled={!s.available}>
              {s.label}{s.available ? "" : " (not generated)"}
            </option>
          ))}
        </select>
        <p className="mt-2 text-xs text-slate-400">{current?.description}</p>
        <div className="mt-3 flex items-center justify-between">
          <Tip content={activeCase ? "Not possible while an investigation is active on this dataset" : "Regenerate the dataset from its seed and remove simulated verification records"}>
            <Button onClick={() => setConfirm(true)} disabled={activeCase || reset.isPending} aria-label="Reset dataset">
              <RotateCcw size={14} /> Reset dataset
            </Button>
          </Tip>
          {reset.isSuccess && <span className="text-xs text-emerald-400">Dataset reset</span>}
        </div>
        {reset.error && <p className="mt-2 text-xs text-red-400">{(reset.error as ApiError).message}</p>}
        <Confirm
          open={confirm}
          onOpenChange={setConfirm}
          title="Reset dataset?"
          body="The simulated factory data is regenerated from its seed. All simulated verification records are removed. Investigation history stays."
          confirmLabel="Reset"
          onConfirm={() => reset.mutate()}
        />
      </Panel>
      <Panel title="Factory overview" right={<span className="text-[11px] text-slate-500">click a station</span>}>
        {ov.isLoading ? (
          <Skeleton className="h-80" />
        ) : ov.error ? (
          <p className="text-sm text-red-400">{(ov.error as ApiError).message}</p>
        ) : ov.data ? (
          <>
            <LineTopology statuses={ov.data.equipment_status} rates={ov.data.fail_rates} selected={selected} onSelect={onSelect} />
            <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
              <dt className="text-slate-500">Data range</dt>
              <dd className="text-right text-slate-300">{ov.data.data_time_range.start.slice(11, 16)}–{ov.data.data_time_range.end.slice(11, 16)} UTC</dd>
              <dt className="text-slate-500">Products</dt>
              <dd className="text-right text-slate-300">{ov.data.record_counts.product_count}</dd>
              <dt className="text-slate-500">Overall FAIL_Rate</dt>
              <dd className="text-right text-slate-300">{fmtRate(ov.data.overall_fail_rate)}</dd>
              <dt className="text-slate-500">Date</dt>
              <dd className="text-right text-slate-300">{fmtTs(ov.data.data_time_range.start).slice(0, 10)}</dd>
            </dl>
          </>
        ) : null}
      </Panel>
    </div>
  );
}
