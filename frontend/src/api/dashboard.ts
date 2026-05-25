import { api } from "./client";

export interface CategoryVolume {
  category: string;
  count: number;
}

export interface SentimentBreakdown {
  category: string;
  positive: number;
  negative: number;
  neutral: number;
  mixed: number;
}

export interface UrgencyCount {
  urgency: "high" | "medium" | "low";
  count: number;
}

export interface DashboardStats {
  run_id: string;
  total_labeled: number;
  other_volume: number;
  other_pct: number;
  volume_by_category: CategoryVolume[];
  sentiment_by_category: SentimentBreakdown[];
  urgency_distribution: UrgencyCount[];
}

export interface ReviewItem {
  id: string;          // feedback_id
  label_id: string;
  run_id: string;
  text: string;
  translated_text: string | null;
  language: string | null;
  category: string | null;
  sentiment: string | null;
  confidence: number | null;
  urgency: string | null;
  review_flags: string[];
}

export interface ReviewPage {
  items: ReviewItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttentionCard {
  type: "taxonomy_gap" | "category";
  category: string | null;
  title: string;
  detail: string;
  action: "refine_taxonomy" | "review_items";
  severity: "high" | "medium";
  count: number;
}

export interface CategoryRow {
  category: string;
  count: number;
  positive: number;
  negative: number;
  neutral: number;
  negative_pct: number;
  high_urgency: number;
  top_phrase: string | null;
  priority_score: number;
}

export interface AttentionSignals {
  total_labeled: number;
  briefing: string;
  attention: AttentionCard[];
  category_table: CategoryRow[];
  verbatim: Record<string, string[]>;
}

export async function getAttentionSignals(runId: string): Promise<AttentionSignals> {
  const { data } = await api.get<AttentionSignals>(`/runs/${runId}/dashboard/attention`);
  return data;
}

export async function getDashboardStats(runId: string): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>(`/runs/${runId}/dashboard`);
  return data;
}

export async function getReviewQueue(
  runId: string,
  page = 1,
  pageSize = 20
): Promise<ReviewPage> {
  const { data } = await api.get<{
    items: Array<{
      feedback_id: string;
      label_id: string;
      original_text: string;
      translated_text: string | null;
      language: string | null;
      suggested_category: string;
      suggested_sentiment: string;
      suggested_urgency: string;
      confidence: number;
      review_flags: string[];
    }>;
    total: number;
    page: number;
    page_size: number;
  }>(`/runs/${runId}/review`, {
    params: { page: page - 1, page_size: pageSize },
  });

  const items: ReviewItem[] = data.items.map((r) => ({
    id: r.feedback_id,
    label_id: r.label_id,
    run_id: runId,
    text: r.original_text,
    translated_text: r.translated_text ?? null,
    language: r.language ?? null,
    category: r.suggested_category,
    sentiment: r.suggested_sentiment,
    confidence: r.confidence,
    urgency: r.suggested_urgency,
    review_flags: r.review_flags,
  }));

  return { items, total: data.total, page, page_size: pageSize };
}

export async function submitReviewDecision(
  runId: string,
  labelId: string,
  action: "confirm" | "edit" | "skip",
  correctedCategory?: string,
  correctedSentiment?: string
): Promise<void> {
  await api.post(`/runs/${runId}/review/decision`, {
    label_id: labelId,
    action,
    corrected_category: correctedCategory ?? null,
    corrected_sentiment: correctedSentiment ?? null,
  });
}

export async function bulkReviewDecision(
  runId: string,
  labelIds: string[],
  action: "confirm" | "edit",
  correctedCategory?: string,
  correctedSentiment?: string
): Promise<{ applied: number }> {
  const { data } = await api.post<{ applied: number }>(`/runs/${runId}/review/bulk`, {
    label_ids: labelIds,
    action,
    corrected_category: correctedCategory ?? null,
    corrected_sentiment: correctedSentiment ?? null,
  });
  return data;
}

export interface KeyphraseCategory {
  category: string;
  phrases: { phrase: string; count: number }[];
}

export interface TimeseriesPoint {
  date: string;
  total: number;
  by_category: Record<string, number>;
}

export async function getKeyphrases(runId: string): Promise<KeyphraseCategory[]> {
  const { data } = await api.get<KeyphraseCategory[]>(`/runs/${runId}/dashboard/keyphrases`);
  return data;
}

export async function getTimeseries(runId: string): Promise<TimeseriesPoint[]> {
  const { data } = await api.get<TimeseriesPoint[]>(`/runs/${runId}/dashboard/timeseries`);
  return data;
}

export function csvExportUrl(runId: string): string {
  return `/api/runs/${runId}/dashboard/export/csv`;
}
