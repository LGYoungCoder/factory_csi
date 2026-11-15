export function fmtTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  return ts.replace("T", " ").replace("Z", " UTC");
}

export function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  return ts.slice(11, 16);
}

export function fmtRate(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(100 * x).toFixed(1)}%`;
}

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—";
  if (p < 0.001) return p.toExponential(1).replace("e-", "e-");
  return p.toFixed(3);
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function fmtUsd(x: number | null | undefined): string {
  if (!x) return "$0.000";
  return `$${x.toFixed(3)}`;
}

export const CATEGORY_LABEL: Record<string, string> = {
  TESTER_MEASUREMENT_DRIFT: "Tester measurement drift",
  PROCESS_PARAMETER_DEVIATION: "Process parameter deviation",
  PRODUCT_MIX_SHIFT: "Product mix shift",
  MATERIAL_LOT_ISSUE: "Material lot issue",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
};

export const VTYPE_LABEL: Record<string, string> = {
  cross_retest: "Cross retest",
  reference_sample_check: "Reference sample check",
  process_config_check: "Process configuration check",
};
