import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, FileText, Trash2, ChevronRight, Pencil, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import { getProject, getProjectRuns, updateProject, type Project } from "@/api/projects";
import {
  getProjectPrompts,
  updateProjectPrompt,
  resetProjectPrompt,
} from "@/api/prompts";
import { deleteRun, type Run } from "@/api/runs";
import { PromptCard } from "@/pages/SettingsPage";
import { cn } from "@/lib/utils";

const STATUS_META: Record<string, { label: string; dot: string }> = {
  pending:     { label: "Pending",       dot: "bg-yellow-400" },
  ingesting:   { label: "Ingesting…",   dot: "bg-blue-400" },
  discovering: { label: "Discovering…", dot: "bg-purple-400" },
  extracting:  { label: "Labeling…",    dot: "bg-orange-400" },
  complete:    { label: "Complete",     dot: "bg-green-400" },
  failed:      { label: "Failed",       dot: "bg-red-400" },
};

const STATUS_ROUTE: Record<string, (id: string) => string> = {
  pending:     (id) => `/run/${id}/discovery`,
  discovering: (id) => `/run/${id}/discovery`,
  extracting:  (id) => `/run/${id}/extract`,
  complete:    (id) => `/run/${id}`,
  failed:      (id) => `/run/${id}`,
};

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"runs" | "prompts">("runs");
  const [confirmDeleteRunId, setConfirmDeleteRunId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId!),
    enabled: !!projectId,
  });

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ["project-runs", projectId],
    queryFn: () => getProjectRuns(projectId!),
    enabled: !!projectId,
    refetchInterval: 5000,
  });

  const { data: prompts } = useQuery({
    queryKey: ["project-prompts", projectId],
    queryFn: () => getProjectPrompts(projectId!),
    enabled: !!projectId && tab === "prompts",
  });

  const updatePromptMutation = useMutation({
    mutationFn: ({ key, content }: { key: string; content: string }) =>
      updateProjectPrompt(projectId!, key, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project-prompts", projectId] }),
  });

  const resetPromptMutation = useMutation({
    mutationFn: (key: string) => resetProjectPrompt(projectId!, key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project-prompts", projectId] }),
  });

  const updateMutation = useMutation({
    mutationFn: (body: { name: string; description: string | null }) =>
      updateProject(projectId!, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      setEditing(false);
    },
  });

  const deleteRunMutation = useMutation({
    mutationFn: deleteRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-runs", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      setConfirmDeleteRunId(null);
    },
  });

  function startEdit(p: Project) {
    setEditName(p.name);
    setEditDesc(p.description ?? "");
    setEditing(true);
  }

  function handleRunClick(run: Run) {
    if (run.status === "ingesting") return;
    const route = STATUS_ROUTE[run.status]?.(run.id) ?? `/run/${run.id}`;
    navigate(route);
  }

  if (projectLoading) return <Spinner />;
  if (!project) return <p className="text-sm text-muted-foreground">Project not found.</p>;

  return (
    <div>
      <PageHeader
        title={project.name}
        subtitle={project.description ?? undefined}
        breadcrumb={[{ label: "Projects", href: "/" }]}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => startEdit(project)}>
              <Pencil className="h-3.5 w-3.5 mr-1.5" />
              Edit
            </Button>
            <Button onClick={() => navigate(`/upload?projectId=${project.id}`)}>
              <Plus className="mr-2 h-4 w-4" />
              New run
            </Button>
          </div>
        }
      />

      {editing && (
        <Card className="mb-6">
          <CardContent className="p-5 space-y-3">
            <p className="text-sm font-medium">Edit project</p>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Name *</label>
              <input
                autoFocus
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Description</label>
              <input
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
                <X className="h-3.5 w-3.5 mr-1" /> Cancel
              </Button>
              <Button
                size="sm"
                disabled={!editName.trim() || updateMutation.isPending}
                onClick={() => updateMutation.mutate({ name: editName.trim(), description: editDesc.trim() || null })}
              >
                <Check className="h-3.5 w-3.5 mr-1" />
                {updateMutation.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Taxonomy badge */}
      {project.taxonomy_run_id && (
        <div className="flex items-center gap-2 mb-5 text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 w-fit">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          Taxonomy inherited from first confirmed run — new runs reuse these categories
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b">
        {(["runs", "prompts"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t === "runs" ? `Runs (${runs?.length ?? 0})` : "Prompts"}
          </button>
        ))}
      </div>

      {/* Runs tab */}
      {tab === "runs" && (
        <>
          {runsLoading && <Spinner />}
          {!runsLoading && runs?.length === 0 && (
            <div className="rounded-xl border-2 border-dashed border-border flex flex-col items-center justify-center py-16 text-center">
              <div className="h-10 w-10 rounded-xl bg-secondary flex items-center justify-center mb-3">
                <FileText className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium mb-1">No runs yet</p>
              <p className="text-sm text-muted-foreground mb-4">Upload a CSV to start analyzing feedback.</p>
              <Button onClick={() => navigate(`/upload?projectId=${project.id}`)}>
                <Plus className="mr-2 h-4 w-4" />
                New run
              </Button>
            </div>
          )}
          <div className="space-y-2">
            {runs?.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                onClick={() => handleRunClick(run)}
                confirmDeleteId={confirmDeleteRunId}
                onRequestDelete={(id) => setConfirmDeleteRunId(id)}
                onCancelDelete={() => setConfirmDeleteRunId(null)}
                onConfirmDelete={(id) => deleteRunMutation.mutate(id)}
                isDeleting={deleteRunMutation.isPending && deleteRunMutation.variables === run.id}
              />
            ))}
          </div>
        </>
      )}

      {/* Prompts tab */}
      {tab === "prompts" && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground mb-4">
            Override prompts for this project. Unchanged prompts use the global default from Settings.
          </p>
          {Object.values(prompts ?? {}).map((p) => (
            <PromptCard
              key={p.key}
              prompt={p}
              onSave={(content) => updatePromptMutation.mutate({ key: p.key, content })}
              onReset={() => resetPromptMutation.mutate(p.key)}
              isSaving={updatePromptMutation.isPending && updatePromptMutation.variables?.key === p.key}
              isResetting={resetPromptMutation.isPending && resetPromptMutation.variables === p.key}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function RunRow({
  run,
  onClick,
  confirmDeleteId,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  isDeleting,
}: {
  run: Run;
  onClick: () => void;
  confirmDeleteId: string | null;
  onRequestDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
  isDeleting: boolean;
}) {
  const meta = STATUS_META[run.status] ?? { label: run.status, dot: "bg-gray-400" };
  const date = new Date(run.started_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
  const isConfirming = confirmDeleteId === run.id;
  const isInProgress = run.status === "ingesting" || run.status === "extracting" || run.status === "discovering";

  return (
    <Card
      className={cn(
        "transition-shadow",
        isInProgress ? "cursor-default" : "cursor-pointer hover:shadow-card-hover",
      )}
      onClick={onClick}
    >
      <CardContent className="p-4 flex items-center gap-4">
        <div className="h-9 w-9 rounded-lg bg-secondary flex items-center justify-center shrink-0">
          <FileText className="h-4 w-4 text-muted-foreground" />
        </div>

        <div className="flex-1 min-w-0">
          <p className="font-medium text-sm truncate">{run.filename}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {date}
            {run.total_rows > 0 && ` · ${run.total_rows.toLocaleString()} rows`}
            {run.flagged_rows > 0 && ` · ${run.flagged_rows} flagged`}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("h-2 w-2 rounded-full", meta.dot)} />
          <span className="text-xs text-muted-foreground">{meta.label}</span>
        </div>

        {isConfirming ? (
          <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <span className="text-xs text-muted-foreground mr-1">Delete?</span>
            <Button size="sm" variant="destructive" className="h-7 text-xs" disabled={isDeleting}
              onClick={() => onConfirmDelete(run.id)}>
              {isDeleting ? "…" : "Yes"}
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-xs"
              onClick={() => onCancelDelete()}>
              Cancel
            </Button>
          </div>
        ) : (
          <button
            className="text-muted-foreground hover:text-destructive transition-colors p-1 shrink-0"
            onClick={(e) => { e.stopPropagation(); onRequestDelete(run.id); }}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}

        {!isConfirming && <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
      </CardContent>
    </Card>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center pt-16">
      <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
