import { api } from "./client";

export interface AppSettings {
  provider: string;
  model: string;
  api_key_set: boolean;
  api_key_preview: string;
  ollama_base_url: string;
  batch_size: number;
  confidence_threshold: number;
  is_configured: boolean;
}

export interface SettingsUpdate {
  provider?: string;
  model?: string;
  api_key?: string;
  ollama_base_url?: string;
  batch_size?: number;
  confidence_threshold?: number;
}

export interface TestResult {
  ok: boolean;
  message: string;
}

export async function getSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>("/settings");
  return data;
}

export async function updateSettings(body: SettingsUpdate): Promise<AppSettings> {
  const { data } = await api.put<AppSettings>("/settings", body);
  return data;
}

export async function getModelList(): Promise<Record<string, string[]>> {
  const { data } = await api.get<Record<string, string[]>>("/settings/models");
  return data;
}

export async function testConnection(): Promise<TestResult> {
  const { data } = await api.post<TestResult>("/settings/test");
  return data;
}

export const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Google Gemini",
  ollama: "Ollama (local)",
};
