import { api } from "./client";

export interface QuerySource {
  text: string;
  category: string;
  sentiment: string;
  urgency: string;
  why_relevant: string;
}

export interface QueryAnswer {
  answer: string;
  key_insights: string[];
  sources: QuerySource[];
  confidence: "high" | "medium" | "low";
}

export interface QueryResponse {
  session_id: string;
  answer: QueryAnswer;
}

export interface QueryMessageRecord {
  id: string;
  question: string;
  answer: string;
  key_insights: string[];
  sources: QuerySource[];
  confidence: "high" | "medium" | "low";
  created_at: string;
}

export interface QuerySession {
  session_id: string;
  started_at: string;
  messages: QueryMessageRecord[];
}

export async function askQuestion(
  runId: string,
  question: string,
  sessionId?: string,
): Promise<QueryResponse> {
  const { data } = await api.post<QueryResponse>(`/runs/${runId}/query`, {
    question,
    session_id: sessionId ?? null,
  });
  return data;
}

export async function getQueryHistory(runId: string): Promise<QuerySession[]> {
  const { data } = await api.get<QuerySession[]>(`/runs/${runId}/query/history`);
  return data;
}
