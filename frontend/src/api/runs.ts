import { api } from "./client";

export interface IngestSummary {
  run_id: string;
  total_rows: number;
  accepted_rows: number;
  duplicate_rows: number;
  skipped_rows: number;
  pii_redactions: number;
  pii_types: Record<string, number>;
  non_english_rows: number;
  language_distribution: Record<string, number>;
  column_warnings?: string[];
}

export interface Run {
  id: string;
  project_id: string | null;
  filename: string;
  status: "pending" | "ingesting" | "discovering" | "extracting" | "complete" | "failed";
  started_at: string;
  completed_at: string | null;
  total_rows: number;
  processed_rows: number;
  flagged_rows: number;
  skipped_rows: number;
  duplicate_rows: number;
  actual_cost: number | null;
  model_used: string | null;
  summary: string | null;
  ai_summary: string | null;
  // Parsed client-side from summary JSON
  ingest_summary?: IngestSummary | null;
}

export interface ColumnMapping {
  feedback_column: string;
  date_column?: string | null;
  source_column?: string | null;
}

export interface IngestResult extends IngestSummary {}

function parseRun(raw: Run): Run {
  if (raw.summary) {
    try {
      raw.ingest_summary = JSON.parse(raw.summary) as IngestSummary;
    } catch {
      raw.ingest_summary = null;
    }
  }
  return raw;
}

export async function listRuns(): Promise<Run[]> {
  const { data } = await api.get<{ runs: Run[]; total: number }>("/runs");
  return data.runs.map(parseRun);
}

export async function getRun(id: string): Promise<Run> {
  const { data } = await api.get<Run>(`/runs/${id}`);
  return parseRun(data);
}

export async function previewCsv(file: File): Promise<{
  columns: string[];
  row_count: number;
  sample_rows: Record<string, string>[];
}> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<{
    columns: string[];
    row_count_estimate: number;
    preview_rows: Record<string, string>[];
  }>("/upload/preview", form, { headers: { "Content-Type": "multipart/form-data" } });
  return {
    columns: data.columns,
    row_count: data.row_count_estimate,
    sample_rows: data.preview_rows,
  };
}

export async function deleteRun(id: string): Promise<void> {
  await api.delete(`/runs/${id}`);
}

export async function generateSummary(runId: string): Promise<{ run_id: string; summary: string }> {
  const { data } = await api.post<{ run_id: string; summary: string }>(`/runs/${runId}/summary`);
  return data;
}

export async function getSummary(runId: string): Promise<{ run_id: string; summary: string } | null> {
  try {
    const { data } = await api.get<{ run_id: string; summary: string }>(`/runs/${runId}/summary`);
    return data;
  } catch {
    return null;
  }
}

export async function ingestCsv(
  file: File,
  mapping: ColumnMapping,
  projectId?: string | null,
): Promise<{ runId: string; summary: IngestSummary }> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams({ feedback_column: mapping.feedback_column });
  if (mapping.date_column) params.set("date_column", mapping.date_column);
  if (mapping.source_column) params.set("source_column", mapping.source_column);
  if (projectId) params.set("project_id", projectId);

  const { data } = await api.post<{ run_id: string; ingest_result: IngestSummary }>(
    `/upload/full?${params.toString()}`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return { runId: data.run_id, summary: data.ingest_result };
}
