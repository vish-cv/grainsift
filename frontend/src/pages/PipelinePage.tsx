import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2, Circle, FileInput, Sparkles, Brain, BarChart3,
  ShieldCheck, Languages, Copy, Layers, DollarSign, Flag, UserCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/Layout";
import { getPipeline, type IngestStage, type DiscoveryStage, type ExtractionStage, type ReviewStage } from "@/api/pipeline";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function langName(code: string): string {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; }
  catch { return code; }
}

function piiLabel(key: string): string {
  const map: Record<string, string> = { email: "email", phone: "phone number", ssn: "SSN", card_number: "card number" };
  return map[key] ?? key;
}

const FLAG_LABEL: Record<string, string> = {
  low_confidence: "Low confidence",
  category_other: "Mapped to other",
  short_text: "Short text",
  schema_retry: "LLM schema retry",
  language_flag: "Non-English",
  random_sample: "Random QA sample",
  high_urgency_low_confidence: "High urgency + low confidence",
};

// ── Stage wrapper ─────────────────────────────────────────────────────────────

function StageCard({
  step,
  icon: Icon,
  title,
  status,
  children,
}: {
  step: number;
  icon: React.ElementType;
  title: string;
  status: "done" | "pending" | "skipped";
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-4">
      {/* Timeline spine */}
      <div className="flex flex-col items-center">
        <div className={cn(
          "h-9 w-9 rounded-full flex items-center justify-center shrink-0 border-2 text-sm font-bold",
          status === "done" ? "bg-green-50 border-green-400 text-green-700" :
          status === "skipped" ? "bg-secondary border-border text-muted-foreground" :
          "bg-secondary border-border text-muted-foreground"
        )}>
          {status === "done" ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <Circle className="h-4 w-4" />}
        </div>
        <div className="w-px flex-1 bg-border mt-1 mb-1 min-h-[16px]" />
      </div>

      {/* Card */}
      <div className="flex-1 pb-6">
        <div className="flex items-center gap-2 mb-2 mt-1.5">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Step {step}</span>
          <span className="text-sm font-semibold text-foreground">{title}</span>
          {status === "skipped" && (
            <Badge variant="outline" className="text-2xs text-muted-foreground ml-1">Not run</Badge>
          )}
        </div>
        {status !== "skipped" && (
          <Card>
            <CardContent className="p-4">{children}</CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

// ── Stage content components ──────────────────────────────────────────────────

function IngestContent({ s }: { s: IngestStage }) {
  const nonEnglish = Object.entries(s.language_distribution).filter(([l]) => l !== "en" && l !== "unknown");
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="Accepted" value={s.accepted_rows} />
        <Metric label="Duplicates removed" value={s.duplicate_rows} muted />
        <Metric label="Skipped" value={s.skipped_rows} muted />
      </div>
      {s.pii_redactions > 0 && (
        <InfoRow icon={ShieldCheck} color="yellow">
          <strong>{s.pii_redactions} PII item{s.pii_redactions !== 1 ? "s" : ""} redacted</strong>
          {Object.keys(s.pii_types).length > 0 && (
            <span className="text-yellow-700 ml-1">
              ({Object.entries(s.pii_types).map(([k, v]) => `${v} ${piiLabel(k)}${v !== 1 ? "s" : ""}`).join(", ")})
            </span>
          )}
        </InfoRow>
      )}
      {s.non_english_rows > 0 && (
        <InfoRow icon={Languages} color="blue">
          <strong>{s.non_english_rows} non-English row{s.non_english_rows !== 1 ? "s" : ""}</strong>
          {nonEnglish.length > 0 && (
            <span className="ml-1">— {nonEnglish.map(([l, n]) => `${n}× ${langName(l)}`).join(", ")}</span>
          )}
          <span className="block text-2xs mt-0.5">Translated automatically before labeling</span>
        </InfoRow>
      )}
      {s.pii_redactions === 0 && s.non_english_rows === 0 && (
        <p className="text-xs text-muted-foreground">No PII detected. All rows in English.</p>
      )}
    </div>
  );
}

function DiscoveryContent({ s }: { s: DiscoveryStage }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {s.created_by === "discovery" ? "AI-suggested" : "Manually defined"} taxonomy · version {s.version}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {s.categories.map((c) => (
          <div key={c.key} className="rounded-lg border border-border bg-secondary/50 px-3 py-1.5 text-xs">
            <span className="font-mono text-muted-foreground mr-1.5">{c.key}</span>
            <span className="font-medium">{c.label}</span>
            {c.description && <span className="text-muted-foreground ml-1.5">— {c.description}</span>}
          </div>
        ))}
        <div className="rounded-lg border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground">
          <span className="font-mono mr-1.5">other</span>auto-assigned
        </div>
      </div>
    </div>
  );
}

function ExtractionContent({ s }: { s: ExtractionStage }) {
  const totalFlagged = Object.values(s.flag_breakdown).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Labeled" value={s.processed} />
        <Metric label="Auto-confirmed" value={s.auto_confirmed} />
        <Metric label="Sent to review" value={s.flagged} accent />
        <Metric label="Cost" value={s.actual_cost_usd != null ? `$${s.actual_cost_usd.toFixed(4)}` : "—"} />
      </div>
      {s.model && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Brain className="h-3.5 w-3.5" />
          Model: <span className="font-mono">{s.model}</span>
        </p>
      )}
      {totalFlagged > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
            <Flag className="h-3.5 w-3.5" />
            Why items were flagged for review
          </p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(s.flag_breakdown)
              .sort(([, a], [, b]) => b - a)
              .map(([flag, count]) => (
                <span key={flag} className="inline-flex items-center gap-1 rounded-md bg-amber-50 border border-amber-200 px-2 py-0.5 text-xs text-amber-800">
                  <span className="font-semibold tabular-nums">{count}</span>
                  {FLAG_LABEL[flag] ?? flag.replace(/_/g, " ")}
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewContent({ s }: { s: ReviewStage }) {
  const pct = s.pct_complete;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="Total flagged" value={s.total_flagged} />
        <Metric label="Reviewed" value={s.reviewed} />
        <Metric label="Pending" value={s.pending} accent={s.pending > 0} />
      </div>
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-muted-foreground">Review progress</span>
          <span className="font-medium tabular-nums">{pct}%</span>
        </div>
        <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500", pct === 100 ? "bg-green-500" : "bg-primary")}
            style={{ width: `${pct}%` }}
          />
        </div>
        {s.pending > 0 && (
          <p className="text-2xs text-muted-foreground mt-1">{s.pending} item{s.pending !== 1 ? "s" : ""} still need human review</p>
        )}
      </div>
    </div>
  );
}

// ── Small shared components ───────────────────────────────────────────────────

function Metric({ label, value, muted, accent }: { label: string; value: number | string; muted?: boolean; accent?: boolean }) {
  return (
    <div className="rounded-lg bg-secondary/60 px-3 py-2">
      <p className={cn("text-base font-bold tabular-nums", muted && "text-muted-foreground", accent && "text-amber-600")}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
      <p className="text-2xs text-muted-foreground">{label}</p>
    </div>
  );
}

function InfoRow({ icon: Icon, color, children }: { icon: React.ElementType; color: "yellow" | "blue"; children: React.ReactNode }) {
  const styles = {
    yellow: "bg-yellow-50 border-yellow-200 text-yellow-800",
    blue: "bg-blue-50 border-blue-200 text-blue-800",
  };
  const iconStyles = { yellow: "text-yellow-600", blue: "text-blue-600" };
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-xs", styles[color])}>
      <Icon className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", iconStyles[color])} />
      <div>{children}</div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function PipelinePage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery({
    queryKey: ["pipeline", rid],
    queryFn: () => getPipeline(rid),
    enabled: !!rid,
  });

  if (isLoading) return <Spinner />;
  if (error) return <p className="text-destructive text-sm">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div>
      <PageHeader
        title="Pipeline audit"
        subtitle={`${data.filename} — ${data.run_status}`}
        breadcrumb={[{ label: "Runs", href: "/" }]}
        action={
          <Button variant="outline" size="sm" onClick={() => navigate(`/run/${rid}/dashboard`)}>
            Dashboard
          </Button>
        }
      />

      <div className="max-w-2xl">
        <StageCard step={1} icon={FileInput} title="Ingest & Clean" status={data.ingest ? "done" : "skipped"}>
          {data.ingest && <IngestContent s={data.ingest} />}
        </StageCard>

        <StageCard step={2} icon={Sparkles} title="Discovery Engine" status={data.discovery ? "done" : "skipped"}>
          {data.discovery && <DiscoveryContent s={data.discovery} />}
        </StageCard>

        <StageCard step={3} icon={Brain} title="Extraction + Validation" status={data.extraction ? "done" : "skipped"}>
          {data.extraction && <ExtractionContent s={data.extraction} />}
        </StageCard>

        <StageCard step={4} icon={UserCheck} title="Human Review" status={data.review ? "done" : "skipped"}>
          {data.review && <ReviewContent s={data.review} />}
        </StageCard>

        {/* Final node */}
        <div className="flex gap-4">
          <div className="flex flex-col items-center">
            <div className={cn(
              "h-9 w-9 rounded-full flex items-center justify-center shrink-0 border-2",
              data.run_status === "complete" ? "bg-green-50 border-green-400" : "bg-secondary border-border"
            )}>
              <BarChart3 className={cn("h-4 w-4", data.run_status === "complete" ? "text-green-600" : "text-muted-foreground")} />
            </div>
          </div>
          <div className="flex-1 mt-1.5">
            <p className="text-sm font-semibold text-foreground">Aggregation &amp; Dashboard</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {data.run_status === "complete"
                ? "All stages complete — view results in the dashboard."
                : "Available once extraction is complete."}
            </p>
            {data.run_status === "complete" && (
              <Button size="sm" className="mt-3" onClick={() => navigate(`/run/${rid}/dashboard`)}>
                View dashboard
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center pt-24">
      <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
