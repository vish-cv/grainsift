import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  DollarSign, Zap, Clock, Layers, ArrowRight, CheckCircle2,
  FileText, Copy, Languages, ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { PageHeader } from "@/components/Layout";
import { estimateCost, runExtraction } from "@/api/extraction";
import { getRun, type IngestSummary } from "@/api/runs";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

function langName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

function piiLabel(key: string): string {
  const map: Record<string, string> = {
    email: "email address",
    phone: "phone number",
    ssn: "SSN",
    card_number: "card number",
  };
  return map[key] ?? key;
}

// ── Ingest Stage Card ─────────────────────────────────────────────────────────

function IngestStageCard({ summary }: { summary: IngestSummary }) {
  const nonEnglish = Object.entries(summary.language_distribution).filter(
    ([lang]) => lang !== "en" && lang !== "unknown"
  );
  const hasLangDetails = nonEnglish.length > 0;
  const hasPiiDetails = Object.keys(summary.pii_types).length > 0;

  return (
    <Card className="border-green-200 bg-green-50/30">
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
          <p className="text-sm font-semibold text-green-800">Stage 1 — Ingest complete</p>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-4">
          <StatPill icon={FileText} label="Accepted" value={summary.accepted_rows} color="text-foreground" />
          <StatPill icon={Copy} label="Duplicates removed" value={summary.duplicate_rows} color="text-muted-foreground" />
          <StatPill icon={Layers} label="Skipped" value={summary.skipped_rows} color="text-muted-foreground" />
        </div>

        <div className="space-y-2 text-xs">
          {summary.pii_redactions > 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-yellow-50 border border-yellow-200 px-3 py-2">
              <ShieldCheck className="h-3.5 w-3.5 text-yellow-600 mt-0.5 shrink-0" />
              <div>
                <span className="font-medium text-yellow-800">
                  {summary.pii_redactions} PII item{summary.pii_redactions !== 1 ? "s" : ""} redacted
                </span>
                {hasPiiDetails && (
                  <span className="text-yellow-700 ml-1">
                    ({Object.entries(summary.pii_types)
                      .map(([k, v]) => `${v} ${piiLabel(k)}${v !== 1 ? "s" : ""}`)
                      .join(", ")})
                  </span>
                )}
              </div>
            </div>
          )}

          {summary.non_english_rows > 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2">
              <Languages className="h-3.5 w-3.5 text-blue-600 mt-0.5 shrink-0" />
              <div>
                <span className="font-medium text-blue-800">
                  {summary.non_english_rows} non-English row{summary.non_english_rows !== 1 ? "s" : ""} detected
                </span>
                {hasLangDetails && (
                  <span className="text-blue-700 ml-1">
                    ({nonEnglish.map(([lang, n]) => `${n} ${langName(lang)}`).join(", ")})
                  </span>
                )}
                <p className="text-blue-600 mt-0.5">These will be flagged for review after labeling.</p>
              </div>
            </div>
          )}

          {summary.pii_redactions === 0 && summary.non_english_rows === 0 && (
            <p className="text-muted-foreground px-1">No PII found, all rows in English.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function StatPill({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-secondary/60 px-3 py-2">
      <Icon className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
      <div>
        <p className={cn("text-sm font-semibold tabular-nums", color)}>{value.toLocaleString()}</p>
        <p className="text-2xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export function ExtractPage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();
  const [started, setStarted] = useState(false);

  // Cost estimate (pre-flight)
  const { data: estimate } = useQuery({
    queryKey: ["estimate", rid],
    queryFn: () => estimateCost(rid),
    enabled: !!rid,
  });

  // Run record — poll while extracting
  const { data: run } = useQuery({
    queryKey: ["run", rid],
    queryFn: () => getRun(rid),
    enabled: !!rid,
    refetchInterval: started ? 2000 : false,
  });

  const isComplete = run?.status === "complete";
  const isFailed = run?.status === "failed";

  const total = run?.total_rows || estimate?.estimated_items || 0;
  const processed = run?.processed_rows ?? 0;
  const flagged = run?.flagged_rows ?? 0;
  const progress = total > 0 ? Math.round((processed / total) * 100) : 0;

  const extractMutation = useMutation({
    mutationFn: () => runExtraction(rid),
    onSuccess: () => setStarted(true),
  });

  const ingestSummary = run?.ingest_summary ?? null;

  return (
    <div>
      <PageHeader
        title="Label feedback"
        subtitle="Review the cost estimate, then start AI labeling."
        breadcrumb={[{ label: "Runs", href: "/" }]}
      />

      <div className="max-w-xl space-y-4">

        {/* Stage 1 — Ingest summary */}
        {ingestSummary && <IngestStageCard summary={ingestSummary} />}

        {/* Stage 2 — Cost estimate */}
        {estimate && !isComplete && (
          <Card>
            <CardContent className="p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-4">
                Stage 2 — AI labeling estimate
              </p>
              <div className="grid grid-cols-2 gap-4">
                {[
                  { icon: Layers, label: "Items to label", value: estimate.estimated_items.toLocaleString() },
                  { icon: Zap, label: "LLM API calls", value: estimate.estimated_api_calls },
                  { icon: DollarSign, label: "Est. cost", value: `$${estimate.estimated_cost_usd.toFixed(4)}` },
                  { icon: Clock, label: "Est. time", value: `~${estimate.estimated_minutes} min` },
                ].map(({ icon: Icon, label, value }) => (
                  <div key={label} className="flex items-start gap-3">
                    <div className="h-8 w-8 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">{label}</p>
                      <p className="text-sm font-semibold">{value}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Stage 2 — Live progress */}
        {started && (
          <Card>
            <CardContent className="p-5 space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground font-medium">
                  {isComplete ? "Labeling complete" : isFailed ? "Labeling failed" : "Labeling in progress…"}
                </span>
                <span className="font-semibold tabular-nums">{progress}%</span>
              </div>

              <Progress value={progress} className="h-2" />

              <div className="grid grid-cols-3 gap-3 pt-1">
                <div className="text-center">
                  <p className="text-lg font-bold tabular-nums">{processed.toLocaleString()}</p>
                  <p className="text-2xs text-muted-foreground">of {total.toLocaleString()} labeled</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold tabular-nums text-yellow-600">{flagged.toLocaleString()}</p>
                  <p className="text-2xs text-muted-foreground">flagged for review</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold tabular-nums">
                    {run?.actual_cost != null ? `$${run.actual_cost.toFixed(4)}` : "—"}
                  </p>
                  <p className="text-2xs text-muted-foreground">cost so far</p>
                </div>
              </div>

              {isComplete && (
                <div className="flex items-center gap-2 text-sm text-green-600 font-medium pt-1">
                  <CheckCircle2 className="h-4 w-4" />
                  All items labeled · {run?.model_used && <span className="text-muted-foreground font-normal ml-1">{run.model_used}</span>}
                </div>
              )}
              {isFailed && (
                <p className="text-sm text-destructive">Labeling failed — check server logs for details.</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-1">
          {!started && (
            <Button variant="outline" onClick={() => navigate(`/run/${rid}/discovery`)}>
              Back
            </Button>
          )}
          {!started && (
            <Button
              onClick={() => { setStarted(true); extractMutation.mutate(); }}
              disabled={!estimate || extractMutation.isPending}
            >
              Start labeling
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          )}
          {isComplete && (
            <Button onClick={() => navigate(`/run/${rid}`)}>
              View results
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          )}
          {isFailed && (
            <Button variant="outline" onClick={() => { setStarted(false); extractMutation.reset(); }}>
              Retry
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
