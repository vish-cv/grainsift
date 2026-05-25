import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ChevronRight, AlertTriangle, FileText, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import { listRuns, deleteRun, type Run } from "@/api/runs";
import { getSettings } from "@/api/settings";
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

export function RunsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 5000,
  });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      setConfirmDeleteId(null);
    },
  });

  function handleRunClick(run: Run) {
    // Don't navigate mid-ingest — nothing useful to show
    if (run.status === "ingesting") return;
    const route = STATUS_ROUTE[run.status]?.(run.id) ?? `/run/${run.id}`;
    navigate(route);
  }

  return (
    <div>
      <PageHeader
        title="Runs"
        subtitle="Each run is one batch of feedback you've uploaded and analyzed."
        action={
          <Button onClick={() => navigate("/upload")}>
            <Plus className="mr-2 h-4 w-4" />
            New run
          </Button>
        }
      />

      {/* Not-configured banner */}
      {settings && !settings.is_configured && (
        <div
          className="flex items-center gap-3 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 mb-6 cursor-pointer hover:bg-amber-100 transition-colors"
          onClick={() => navigate("/settings")}
        >
          <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
          <p className="text-sm text-amber-800 flex-1">
            No AI model configured yet — GrainSift can't analyze feedback until you add an API key.
          </p>
          <span className="text-sm font-medium text-amber-800 shrink-0">Configure →</span>
        </div>
      )}

      {isLoading && <Spinner />}

      {/* Empty state */}
      {!isLoading && runs?.length === 0 && (
        <div className="rounded-xl border-2 border-dashed border-border flex flex-col items-center justify-center py-20 text-center">
          <div className="h-12 w-12 rounded-xl bg-secondary flex items-center justify-center mb-4">
            <FileText className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="text-sm font-medium mb-1">No runs yet</p>
          <p className="text-sm text-muted-foreground mb-5">Upload a CSV to get started.</p>
          <Button onClick={() => navigate("/upload")}>
            <Plus className="mr-2 h-4 w-4" />
            New run
          </Button>
        </div>
      )}

      {/* Run list */}
      <div className="space-y-2">
        {runs?.map((run) => (
          <RunRow
            key={run.id}
            run={run}
            onClick={() => handleRunClick(run)}
            confirmDeleteId={confirmDeleteId}
            onRequestDelete={(id) => setConfirmDeleteId(id)}
            onCancelDelete={() => setConfirmDeleteId(null)}
            onConfirmDelete={(id) => deleteMutation.mutate(id)}
            isDeleting={deleteMutation.isPending && deleteMutation.variables === run.id}
          />
        ))}
      </div>
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

        {/* Delete zone */}
        {isConfirming ? (
          <div
            className="flex items-center gap-1.5 shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="text-xs text-muted-foreground mr-1">Delete?</span>
            <Button
              size="sm"
              variant="destructive"
              className="h-7 text-xs"
              disabled={isDeleting}
              onClick={() => onConfirmDelete(run.id)}
            >
              {isDeleting ? "…" : "Yes"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => onCancelDelete()}
            >
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

        {!isConfirming && (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
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
