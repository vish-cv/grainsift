import { api } from "./client";

export interface CostEstimate {
  estimated_items: number;
  estimated_api_calls: number;
  estimated_cost_usd: number;
  estimated_minutes: number;
}

export async function estimateCost(runId: string): Promise<CostEstimate> {
  const { data } = await api.get<CostEstimate>(`/runs/${runId}/estimate`);
  return data;
}

export async function runExtraction(runId: string): Promise<{ status: string; run_id: string }> {
  const { data } = await api.post<{ status: string; run_id: string }>(`/runs/${runId}/extract`);
  return data;
}
