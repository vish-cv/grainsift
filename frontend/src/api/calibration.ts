import { api } from "./client";

export interface CategoryHumanStat {
  category: string;
  reviewed: number;
  confirmed: number;
  corrected: number;
  accuracy: number;
}

export interface CategoryConsistency {
  category: string;
  matches: number;
  total: number;
  agreement: number;
}

export interface ConfusionPair {
  from_cat: string;
  to_cat: string;
  count: number;
}

export interface ConfidenceBucket {
  label: string;
  count: number;
  accuracy: number | null;
}

export interface CalibrationReport {
  // From human review
  total_reviewed: number;
  human_accuracy: number | null;
  human_correction_rate: number | null;
  per_category_human: CategoryHumanStat[];

  // Confusion matrix
  confusion_pairs: ConfusionPair[];

  // Confidence calibration buckets
  confidence_buckets: ConfidenceBucket[];

  // From self-consistency check
  has_self_check: boolean;
  sample_size: number | null;
  category_agreement: number | null;
  sentiment_agreement: number | null;
  urgency_agreement: number | null;
  per_category_consistency: CategoryConsistency[];
  calibrated_at: string | null;
}

export async function getCalibration(runId: string): Promise<CalibrationReport> {
  const { data } = await api.get<CalibrationReport>(`/runs/${runId}/calibration`);
  return data;
}

export async function runCalibration(runId: string, sampleSize = 20): Promise<CalibrationReport> {
  const { data } = await api.post<CalibrationReport>(
    `/runs/${runId}/calibration`,
    null,
    { params: { sample_size: sampleSize } },
  );
  return data;
}
