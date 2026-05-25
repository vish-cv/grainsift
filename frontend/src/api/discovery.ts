import { api } from "./client";

export interface EnumCategory {
  key: string;
  label: string;
  description: string;
}

export interface EnumConfig {
  id: string;
  run_id: string;
  version: number;
  categories: Record<string, unknown>;
}

export interface TaxonomySource {
  run_id: string;
  filename: string;
  category_count: number;
  categories: EnumCategory[];
}

export async function startDiscovery(
  runId: string,
  lockedCategories?: EnumCategory[],
): Promise<EnumCategory[]> {
  const body = lockedCategories && lockedCategories.length > 0
    ? { locked_categories: lockedCategories }
    : null;
  const { data } = await api.post<EnumCategory[]>(`/runs/${runId}/discovery/start`, body);
  return data;
}

export async function confirmDiscovery(
  runId: string,
  categories: EnumCategory[],
  createdBy?: string,
): Promise<EnumConfig> {
  const { data } = await api.post<EnumConfig>(`/runs/${runId}/discovery/confirm`, {
    run_id: runId,
    categories,
    created_by: createdBy,
  });
  return data;
}

export async function getEnumConfig(runId: string): Promise<EnumConfig | null> {
  try {
    const { data } = await api.get<EnumConfig>(`/runs/${runId}/discovery/config`);
    return data;
  } catch {
    return null;
  }
}

export async function getEnumCategories(runId: string): Promise<EnumCategory[]> {
  const { data } = await api.get<EnumCategory[]>(`/runs/${runId}/discovery/config/categories`);
  return data;
}

export async function getAvailableTaxonomies(runId: string): Promise<TaxonomySource[]> {
  const { data } = await api.get<TaxonomySource[]>(`/runs/${runId}/discovery/available-taxonomies`);
  return data;
}

export async function importTaxonomy(runId: string, sourceRunId: string): Promise<EnumCategory[]> {
  const { data } = await api.post<EnumCategory[]>(`/runs/${runId}/discovery/import/${sourceRunId}`);
  return data;
}

export async function useProjectTaxonomy(runId: string): Promise<EnumCategory[]> {
  const { data } = await api.post<EnumCategory[]>(`/runs/${runId}/discovery/use-project-taxonomy`);
  return data;
}
