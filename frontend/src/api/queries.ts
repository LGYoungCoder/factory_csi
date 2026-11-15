import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { CaseDetail, CaseSummary, LlmStatus, McpCall, Overview, Scenario, Trends } from "./types";

export const keys = {
  llm: ["llm"] as const,
  scenarios: ["scenarios"] as const,
  overview: (ds: string) => ["overview", ds] as const,
  trends: (ds: string, b: number) => ["trends", ds, b] as const,
  equipment: (ds: string, e: string) => ["equipment", ds, e] as const,
  cases: (ds: string) => ["cases", ds] as const,
  case: (id: string) => ["case", id] as const,
  mcp: (id: string) => ["mcp", id] as const,
  report: (id: string) => ["report", id] as const,
  evidence: (id: string, ev: string) => ["evidence", id, ev] as const,
};

export const useLlmStatus = () =>
  useQuery({ queryKey: keys.llm, queryFn: () => api.get<LlmStatus>("/llm/status"), refetchInterval: 30_000 });

export const useScenarios = () => useQuery({ queryKey: keys.scenarios, queryFn: () => api.get<Scenario[]>("/scenarios") });

export const useOverview = (ds: string) =>
  useQuery({ queryKey: keys.overview(ds), queryFn: () => api.get<Overview>(`/datasets/${ds}/overview`), enabled: !!ds });

export const useTrends = (ds: string, bucket: number) =>
  useQuery({
    queryKey: keys.trends(ds, bucket),
    queryFn: () => api.get<Trends>(`/datasets/${ds}/trends?bucket_minutes=${bucket}`),
    enabled: !!ds,
  });

export const useEquipment = (ds: string, eid: string | null) =>
  useQuery({
    queryKey: keys.equipment(ds, eid ?? ""),
    queryFn: () => api.get<Record<string, unknown>>(`/datasets/${ds}/equipment/${eid}`),
    enabled: !!ds && !!eid,
  });

export const useCases = (ds: string) =>
  useQuery({ queryKey: keys.cases(ds), queryFn: () => api.get<CaseSummary[]>(`/cases?dataset_id=${ds}`), enabled: !!ds });

export const useCase = (id: string | null) =>
  useQuery({ queryKey: keys.case(id ?? ""), queryFn: () => api.get<CaseDetail>(`/cases/${id}`), enabled: !!id });

export const useMcpCalls = (id: string | null) =>
  useQuery({ queryKey: keys.mcp(id ?? ""), queryFn: () => api.get<McpCall[]>(`/cases/${id}/mcp-calls`), enabled: !!id });

export const useEvidenceDetail = (caseId: string | null, ev: string | null) =>
  useQuery({
    queryKey: keys.evidence(caseId ?? "", ev ?? ""),
    queryFn: () =>
      api.get<{ evidence: unknown; source_records: { ref: string; table: string; record: Record<string, unknown> }[]; source_records_error: string | null }>(
        `/cases/${caseId}/evidence/${ev}`,
      ),
    enabled: !!caseId && !!ev,
  });

export const useReport = (id: string) =>
  useQuery({
    queryKey: keys.report(id),
    queryFn: () => api.get<{ version: number; markdown: string; report: Record<string, unknown> }>(`/cases/${id}/report`),
  });

export function useRefreshLlm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<LlmStatus>("/llm/status/refresh"),
    onSuccess: (d) => qc.setQueryData(keys.llm, d),
  });
}

export function useResetDataset(ds: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/datasets/${ds}/reset`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overview", ds] });
      qc.invalidateQueries({ queryKey: ["trends", ds] });
      qc.invalidateQueries({ queryKey: ["equipment", ds] });
    },
  });
}

export function useStartCase(ds: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<CaseDetail>("/cases", { dataset_id: ds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.cases(ds) }),
  });
}

export function useDecision(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { action: string; proposal_id?: string; note?: string }) => api.post(`/cases/${caseId}/decision`, body),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.case(caseId) }),
  });
}

export function useRetry(caseId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/cases/${caseId}/retry`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.case(caseId) }),
  });
}
