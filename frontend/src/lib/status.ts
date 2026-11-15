export type StatusColor = "GREEN" | "ORANGE" | "RED" | "GREY";

export const STATUS_STYLE: Record<StatusColor, { label: string; fill: string; stroke: string; text: string; icon: string }> = {
  GREEN: { label: "Normal", fill: "#064e3b", stroke: "#10b981", text: "text-emerald-400", icon: "●" },
  ORANGE: { label: "Warning", fill: "#451a03", stroke: "#f59e0b", text: "text-amber-400", icon: "▲" },
  RED: { label: "Anomaly", fill: "#450a0a", stroke: "#ef4444", text: "text-red-400", icon: "■" },
  GREY: { label: "Unknown", fill: "#1e293b", stroke: "#64748b", text: "text-slate-400", icon: "○" },
};

export function statusStyle(s: string | undefined) {
  return STATUS_STYLE[(s as StatusColor) in STATUS_STYLE ? (s as StatusColor) : "GREY"];
}

export const SUPPORT_STYLE: Record<string, string> = {
  HIGH: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  MEDIUM: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  LOW: "bg-slate-500/15 text-slate-300 border-slate-500/40",
  INSUFFICIENT: "bg-slate-800 text-slate-400 border-slate-600",
};

export const SUPPORT_LABEL: Record<string, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low", INSUFFICIENT: "Insufficient" };

export const SOURCE_STYLE: Record<string, string> = {
  MES: "bg-indigo-500/15 text-indigo-300",
  PPM: "bg-cyan-500/15 text-cyan-300",
  EOL: "bg-sky-500/15 text-sky-300",
  ANALYTICS: "bg-slate-500/20 text-slate-300",
  VERIFICATION: "bg-emerald-500/15 text-emerald-300",
};

export const ACTIVE_STATUSES = ["CREATED", "RUNNING", "AWAITING_APPROVAL", "CONCLUDING"];

/** Evidence related to an equipment id (record_refs, data or equipment list mention it). */
export function relatesTo(ev: { equipment?: string[]; record_refs: string[]; data: unknown }, eid: string): boolean {
  if (ev.equipment?.includes(eid)) return true;
  return JSON.stringify(ev.data ?? {}).includes(`"${eid}"`);
}
