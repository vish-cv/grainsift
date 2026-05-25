import { useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { UploadCloud, FileText, X, ArrowRight } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/Layout";
import { cn } from "@/lib/utils";
import { previewCsv, ingestCsv, type ColumnMapping } from "@/api/runs";
import { getProject } from "@/api/projects";

type Step = "drop" | "map" | "ingesting";

interface Preview {
  columns: string[];
  row_count: number;
  sample_rows: Record<string, string>[];
}

export function UploadPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("projectId") ?? undefined;

  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId!),
    enabled: !!projectId,
  });

  const [step, setStep] = useState<Step>("drop");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>({ feedback_column: "" });
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: previewCsv,
    onSuccess: (data) => {
      setPreview(data);
      const guessedFeedback = data.columns.find((c) =>
        /feedback|comment|review|text|message|body/i.test(c)
      ) ?? data.columns[0];
      const guessedDate = data.columns.find((c) => /date|time|created|at$/i.test(c)) ?? null;
      const guessedSource = data.columns.find((c) => /source|channel|platform/i.test(c)) ?? null;
      setMapping({ feedback_column: guessedFeedback, date_column: guessedDate, source_column: guessedSource });
      setStep("map");
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const ingestMutation = useMutation({
    mutationFn: ({ f, m }: { f: File; m: ColumnMapping }) => ingestCsv(f, m, projectId),
    onSuccess: ({ runId }) => navigate(`/run/${runId}/discovery`),
    onError: (e: Error) => { setError(e.message); setStep("map"); },
  });

  const handleFiles = useCallback((files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    if (!f.name.endsWith(".csv")) { setError("Only CSV files are supported."); return; }
    setFile(f);
    setError(null);
    previewMutation.mutate(f);
  }, [previewMutation]);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  function handleIngest() {
    if (!file || !mapping.feedback_column) return;
    setStep("ingesting");
    ingestMutation.mutate({ f: file, m: mapping });
  }

  const breadcrumb = project
    ? [{ label: "Projects", href: "/" }, { label: project.name, href: `/projects/${project.id}` }]
    : [{ label: "Projects", href: "/" }];

  /* ── Drop zone ── */
  if (step === "drop" || previewMutation.isPending) {
    return (
      <div>
        <PageHeader
          title="Upload feedback"
          subtitle={project ? `New run in "${project.name}"` : "Drop a CSV to start a new analysis run."}
          breadcrumb={breadcrumb}
        />
        <div className="max-w-lg">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("csv-input")?.click()}
            className={cn(
              "border-2 border-dashed rounded-xl flex flex-col items-center justify-center gap-3 py-16 cursor-pointer transition-colors",
              dragOver ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-secondary/50"
            )}
          >
            <input id="csv-input" type="file" accept=".csv" className="hidden"
              onChange={(e) => handleFiles(e.target.files)} />
            {previewMutation.isPending ? (
              <div className="flex flex-col items-center gap-2">
                <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-muted-foreground">Reading file…</p>
              </div>
            ) : (
              <>
                <div className="h-12 w-12 rounded-xl bg-secondary flex items-center justify-center">
                  <UploadCloud className="h-6 w-6 text-muted-foreground" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium">Drop CSV here or click to browse</p>
                  <p className="text-xs text-muted-foreground mt-0.5">Supports up to 50,000 rows</p>
                </div>
              </>
            )}
          </div>
          {error && <p className="text-destructive text-sm mt-3">{error}</p>}
        </div>
      </div>
    );
  }

  /* ── Column mapping ── */
  if (step === "map" && preview && file) {
    return (
      <div>
        <PageHeader
          title="Map columns"
          subtitle="Tell GrainSift which column contains the feedback text."
          breadcrumb={breadcrumb}
        />
        <div className="max-w-2xl space-y-5">

          {/* File info bar */}
          <div className="flex items-center gap-3 rounded-lg bg-secondary px-4 py-3">
            <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{file.name}</p>
              <p className="text-xs text-muted-foreground">{preview.row_count.toLocaleString()} rows detected</p>
            </div>
            <button onClick={() => { setFile(null); setStep("drop"); setPreview(null); }}
              className="text-muted-foreground hover:text-foreground transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Mapping card */}
          <Card>
            <CardContent className="p-5 space-y-4">
              <ColumnSelect label="Feedback text *" columns={preview.columns}
                value={mapping.feedback_column}
                onChange={(v) => setMapping((m) => ({ ...m, feedback_column: v }))} />
              <ColumnSelect label="Date (optional)" columns={["(none)", ...preview.columns]}
                value={mapping.date_column ?? "(none)"}
                onChange={(v) => setMapping((m) => ({ ...m, date_column: v === "(none)" ? null : v }))} />
              <ColumnSelect label="Source / channel (optional)" columns={["(none)", ...preview.columns]}
                value={mapping.source_column ?? "(none)"}
                onChange={(v) => setMapping((m) => ({ ...m, source_column: v === "(none)" ? null : v }))} />
            </CardContent>
          </Card>

          {/* Preview table */}
          <Card>
            <div className="px-5 py-3 border-b">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Preview — first 5 rows</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-secondary/50">
                    {preview.columns.slice(0, 4).map((c) => (
                      <th key={c} className={cn(
                        "px-4 py-2.5 text-left font-medium",
                        c === mapping.feedback_column ? "text-primary" : "text-muted-foreground"
                      )}>
                        {c}
                        {c === mapping.feedback_column && (
                          <Badge variant="secondary" className="ml-1.5 text-2xs py-0 px-1.5">feedback</Badge>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, i) => (
                    <tr key={i} className="border-b last:border-0">
                      {preview.columns.slice(0, 4).map((c) => (
                        <td key={c} className={cn(
                          "px-4 py-2.5 max-w-[220px] truncate",
                          c === mapping.feedback_column && "font-medium"
                        )}>
                          {row[c] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {error && <p className="text-destructive text-sm">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" onClick={() => { setFile(null); setStep("drop"); setPreview(null); }}>
              Back
            </Button>
            <Button onClick={handleIngest} disabled={!mapping.feedback_column}>
              Import & continue
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Ingesting ── */
  return (
    <div className="flex flex-col items-center justify-center gap-4 pt-24">
      <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      <p className="text-sm text-muted-foreground">Importing {file?.name}…</p>
    </div>
  );
}

function ColumnSelect({ label, columns, value, onChange }: {
  label: string; columns: string[]; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-4">
      <label className="w-44 text-sm font-medium shrink-0 text-muted-foreground">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </div>
  );
}
