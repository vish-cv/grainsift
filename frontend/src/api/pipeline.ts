import { api } from "./client";

export interface IngestStage {
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

export interface DiscoveryCategory {
  key: string;
  label: string;
  description: string;
}

export interface DiscoveryStage {
  version: number;
  category_count: number;
  categories: DiscoveryCategory[];
  created_by: string;
}

export interface ExtractionStage {
  processed: number;
  flagged: number;
  auto_confirmed: number;
  actual_cost_usd: number | null;
  model: string | null;
  flag_breakdown: Record<string, number>;
  low_confidence_categories?: string[];
}

export interface ReviewStage {
  total_flagged: number;
  reviewed: number;
  pending: number;
  pct_complete: number;
}

export interface PipelineData {
  run_id: string;
  run_status: string;
  filename: string;
  ingest: IngestStage | null;
  discovery: DiscoveryStage | null;
  extraction: ExtractionStage | null;
  review: ReviewStage | null;
}

export interface LabeledItem {
  id: string;
  text: string;
  language: string | null;
  source_channel: string | null;
  date: string | null;
  category: string;
  sentiment: string;
  urgency: string;
  key_phrase: string | null;
  confidence: number;
  source: string;
  review_flags: string[];
}

export interface LabelsPage {
  items: LabeledItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function getPipeline(runId: string): Promise<PipelineData> {
  const { data } = await api.get<PipelineData>(`/runs/${runId}/pipeline`);
  return data;
}

export interface LabelFilters {
  search?: string;
  category?: string;
  sentiment?: string;
  urgency?: string;
}

export async function getLabels(runId: string, page = 0, pageSize = 50, filters?: LabelFilters): Promise<LabelsPage> {
  const { data } = await api.get<LabelsPage>(`/runs/${runId}/dashboard/labels`, {
    params: { page, page_size: pageSize, ...filters },
  });
  return data;
}
