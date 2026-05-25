import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, FolderOpen, Trash2, ChevronRight, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import { listProjects, createProject, deleteProject, type Project } from "@/api/projects";
import { getSettings } from "@/api/settings";
import { cn } from "@/lib/utils";

export function ProjectsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const createMutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setShowCreate(false);
      navigate(`/projects/${project.id}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setConfirmDeleteId(null);
    },
  });

  return (
    <div>
      <PageHeader
        title="Projects"
        subtitle="Group related analysis runs under a shared taxonomy."
        action={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New project
          </Button>
        }
      />

      {settings && !settings.is_configured && (
        <div
          className="flex items-center gap-3 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 mb-6 cursor-pointer hover:bg-amber-100 transition-colors"
          onClick={() => navigate("/settings")}
        >
          <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
          <p className="text-sm text-amber-800 flex-1">
            No AI model configured yet — add an API key before analyzing feedback.
          </p>
          <span className="text-sm font-medium text-amber-800 shrink-0">Configure →</span>
        </div>
      )}

      {showCreate && (
        <CreateProjectForm
          onSubmit={(name, description) => createMutation.mutate({ name, description })}
          onCancel={() => setShowCreate(false)}
          isLoading={createMutation.isPending}
        />
      )}

      {isLoading && <Spinner />}

      {!isLoading && projects?.length === 0 && !showCreate && (
        <div className="rounded-xl border-2 border-dashed border-border flex flex-col items-center justify-center py-20 text-center">
          <div className="h-12 w-12 rounded-xl bg-secondary flex items-center justify-center mb-4">
            <FolderOpen className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium mb-1">No projects yet</p>
          <p className="text-sm text-muted-foreground mb-5">
            Create a project to group runs under a shared set of categories.
          </p>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New project
          </Button>
        </div>
      )}

      <div className="space-y-2">
        {projects?.map((project) => (
          <ProjectRow
            key={project.id}
            project={project}
            onClick={() => navigate(`/projects/${project.id}`)}
            confirmDeleteId={confirmDeleteId}
            onRequestDelete={(id) => setConfirmDeleteId(id)}
            onCancelDelete={() => setConfirmDeleteId(null)}
            onConfirmDelete={(id) => deleteMutation.mutate(id)}
            isDeleting={deleteMutation.isPending && deleteMutation.variables === project.id}
          />
        ))}
      </div>
    </div>
  );
}

function ProjectRow({
  project,
  onClick,
  confirmDeleteId,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  isDeleting,
}: {
  project: Project;
  onClick: () => void;
  confirmDeleteId: string | null;
  onRequestDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
  isDeleting: boolean;
}) {
  const isConfirming = confirmDeleteId === project.id;
  const date = new Date(project.created_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-card-hover"
      onClick={onClick}
    >
      <CardContent className="p-4 flex items-center gap-4">
        <div className="h-9 w-9 rounded-lg bg-blue-50 dark:bg-blue-950 flex items-center justify-center shrink-0">
          <FolderOpen className="h-4 w-4 text-blue-500" />
        </div>

        <div className="flex-1 min-w-0">
          <p className="font-medium text-sm truncate">{project.name}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {date}
            {" · "}
            {project.run_count === 0
              ? "No runs yet"
              : `${project.run_count} run${project.run_count !== 1 ? "s" : ""}`}
            {project.description && ` · ${project.description}`}
          </p>
        </div>

        {project.taxonomy_run_id && (
          <span className="text-xs bg-green-50 text-green-700 border border-green-200 rounded-full px-2 py-0.5 shrink-0">
            Taxonomy set
          </span>
        )}

        {isConfirming ? (
          <div
            className="flex items-center gap-1.5 shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="text-xs text-muted-foreground mr-1">Delete project + all runs?</span>
            <Button
              size="sm"
              variant="destructive"
              className="h-7 text-xs"
              disabled={isDeleting}
              onClick={() => onConfirmDelete(project.id)}
            >
              {isDeleting ? "…" : "Yes, delete"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={(e) => { e.stopPropagation(); onCancelDelete(); }}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <button
            className="text-muted-foreground hover:text-destructive transition-colors p-1 shrink-0"
            onClick={(e) => { e.stopPropagation(); onRequestDelete(project.id); }}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}

        {!isConfirming && <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
      </CardContent>
    </Card>
  );
}

function CreateProjectForm({
  onSubmit,
  onCancel,
  isLoading,
}: {
  onSubmit: (name: string, description: string | null) => void;
  onCancel: () => void;
  isLoading: boolean;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  return (
    <Card className="mb-4">
      <CardContent className="p-5 space-y-4">
        <p className="text-sm font-medium">New project</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Project name *</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) onSubmit(name.trim(), description.trim() || null); }}
              placeholder="e.g. App Store Reviews Q2 2026"
              className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Description (optional)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Customer feedback from iOS and Android app stores"
              className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        </div>
        <div className={cn("flex gap-2 justify-end")}>
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>Cancel</Button>
          <Button
            onClick={() => onSubmit(name.trim(), description.trim() || null)}
            disabled={!name.trim() || isLoading}
          >
            {isLoading ? "Creating…" : "Create project"}
          </Button>
        </div>
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
