import { api } from "./client";
import type { Run } from "./runs";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  taxonomy_run_id: string | null;
  created_at: string;
  run_count: number;
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
}

export async function listProjects(): Promise<Project[]> {
  const { data } = await api.get<Project[]>("/projects");
  return data;
}

export async function createProject(body: ProjectCreate): Promise<Project> {
  const { data } = await api.post<Project>("/projects", body);
  return data;
}

export async function getProject(id: string): Promise<Project> {
  const { data } = await api.get<Project>(`/projects/${id}`);
  return data;
}

export async function updateProject(id: string, body: ProjectCreate): Promise<Project> {
  const { data } = await api.patch<Project>(`/projects/${id}`, body);
  return data;
}

export async function deleteProject(id: string): Promise<void> {
  await api.delete(`/projects/${id}`);
}

export async function getProjectRuns(projectId: string): Promise<Run[]> {
  const { data } = await api.get<{ runs: Run[]; total: number }>(`/projects/${projectId}/runs`);
  return data.runs;
}
