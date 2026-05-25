import { api } from "./client";

export interface PromptItem {
  key: string;
  label: string;
  description: string;
  required_vars: string[];
  read_only: boolean;
  content: string;
  source: "default" | "global" | "project";
}

export type PromptsMap = Record<string, PromptItem>;

export async function getGlobalPrompts(): Promise<PromptsMap> {
  const { data } = await api.get<PromptsMap>("/prompts");
  return data;
}

export async function updateGlobalPrompt(key: string, content: string): Promise<PromptItem> {
  const { data } = await api.put<PromptItem>(`/prompts/${key}`, { content });
  return data;
}

export async function resetGlobalPrompt(key: string): Promise<void> {
  await api.delete(`/prompts/${key}`);
}

export async function getProjectPrompts(projectId: string): Promise<PromptsMap> {
  const { data } = await api.get<PromptsMap>(`/projects/${projectId}/prompts`);
  return data;
}

export async function updateProjectPrompt(
  projectId: string,
  key: string,
  content: string,
): Promise<PromptItem> {
  const { data } = await api.put<PromptItem>(`/projects/${projectId}/prompts/${key}`, { content });
  return data;
}

export async function resetProjectPrompt(projectId: string, key: string): Promise<void> {
  await api.delete(`/projects/${projectId}/prompts/${key}`);
}
