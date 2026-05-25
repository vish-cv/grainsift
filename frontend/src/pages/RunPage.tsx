import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, Circle, ShieldCheck, Languages, Flag,
  Brain, Sparkles, FileInput, UserCheck, ChevronLeft, ChevronRight,
  ArrowRight, AlertCircle, Send, MessageSquare, FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import { getRun, generateSummary, type Run } from "@/api/runs";
import { getPipeline, getLabels, type LabeledItem, type LabelFilters } from "@/api/pipeline";
import { getEnumCategories } from "@/api/discovery";
import { askQuestion, getQueryHistory, type QueryAnswer, type QuerySource } from "@/api/query";
import { getCalibration, runCalibration, type CalibrationReport } from "@/api/calibration";
import { getAttentionSignals, csvExportUrl, type AttentionCard as AttentionCardData, type CategoryRow } from "@/api/dashboard";
import { cn } from "@/lib/utils";

type Tab = "overview" | "insights" | "data" | "ask" | "quality";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function langName(code: string) {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; }
  catch { return code; }
}
function piiLabel(key: string) {
  return ({
    email: "email", phone: "phone number", ssn: "SSN", card_number: "card number",
    ip_address: "IP address", address: "street address", name: "name",
  } as Record<string, string>)[key] ?? key.replace(/_/g, " ");
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

const URGENCY_BADGE: Record<string, string> = {
  high:   "text-orange-700 bg-orange-50 border-orange-200",
  medium: "text-yellow-700 bg-yellow-50 border-yellow-200",
  low:    "text-muted-foreground bg-secondary border-border",
};
const SENTIMENT_BADGE: Record<string, string> = {
  positive: "text-green-700 bg-green-50 border-green-200",
  negative: "text-red-700 bg-red-50 border-red-200",
  neutral:  "text-muted-foreground bg-secondary border-border",
  mixed:    "text-yellow-700 bg-yellow-50 border-yellow-200",
};
const SENTIMENT_COLORS: Record<string, string> = {
  positive: "bg-green-500", negative: "bg-red-400",
  neutral: "bg-gray-300",  mixed: "bg-yellow-400",
};
const URGENCY_CONFIG = [
  { key: "high"   as const, label: "High",   bar: "bg-orange-400", text: "text-orange-700" },
  { key: "medium" as const, label: "Medium", bar: "bg-yellow-400", text: "text-yellow-700" },
  { key: "low"    as const, label: "Low",    bar: "bg-gray-300",   text: "text-muted-foreground" },
];

const STATUS_LABEL: Record<string, { label: string; dot: string }> = {
  pending:     { label: "Pending",       dot: "bg-yellow-400" },
  ingesting:   { label: "Ingesting…",   dot: "bg-blue-400" },
  discovering: { label: "Discovering…", dot: "bg-purple-400" },
  extracting:  { label: "Labeling…",    dot: "bg-orange-400" },
  complete:    { label: "Complete",     dot: "bg-green-400" },
  failed:      { label: "Failed",       dot: "bg-red-400" },
};

// ─── Tab bar ──────────────────────────────────────────────────────────────────

function TabBar({ active, onChange, reviewPending }: {
  active: Tab;
  onChange: (t: Tab) => void;
  reviewPending: number;
}) {
  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "overview",  label: "Overview" },
    { id: "insights",  label: "Insights" },
    { id: "data",      label: "Data" },
    { id: "ask",       label: "Ask AI" },
    { id: "quality",   label: "Quality" },
  ];
  return (
    <div className="flex border-b border-border mb-6 -mt-2">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            "relative px-4 py-2.5 text-sm font-medium transition-colors",
            active === t.id
              ? "text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t.label}
          {t.badge != null && t.badge > 0 && (
            <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] px-1 rounded-full bg-amber-500 text-white text-2xs font-bold">
              {t.badge}
            </span>
          )}
          {active === t.id && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-full" />
          )}
        </button>
      ))}
    </div>
  );
}

// ─── Overview tab ─────────────────────────────────────────────────────────────

function OverviewTab({ runId, run, navigate }: { runId: string; run: Run; navigate: ReturnType<typeof useNavigate> }) {
  const qc = useQueryClient();

  const { data: pipeline, isLoading } = useQuery({
    queryKey: ["pipeline", runId],
    queryFn: () => getPipeline(runId),
  });

  const summaryMutation = useMutation({
    mutationFn: () => generateSummary(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", runId] }),
  });

  if (isLoading) return <TabSpinner />;
  if (!pipeline) return null;

  const { ingest, discovery, extraction, review } = pipeline;

  return (
    <div className="space-y-5 max-w-2xl">

      {/* Stage 1 — Ingest */}
      {ingest && (
        <Section icon={FileInput} title="Ingest & Clean" done>
          {/* Counts row */}
          <div className="grid grid-cols-3 gap-3 mb-3">
            <Stat label="Accepted" value={ingest.accepted_rows} />
            <Stat label="Duplicates removed" value={ingest.duplicate_rows} muted />
            <Stat label="Skipped" value={ingest.skipped_rows} muted />
          </div>
          {/* PII */}
          {ingest.pii_redactions > 0 && (
            <Pill icon={ShieldCheck} color="yellow">
              <strong>{ingest.pii_redactions} PII item{ingest.pii_redactions !== 1 ? "s" : ""} redacted</strong>
              {Object.keys(ingest.pii_types).length > 0 && (
                <span className="ml-1">
                  ({Object.entries(ingest.pii_types).map(([k, v]) => `${v} ${piiLabel(k)}${v !== 1 ? "s" : ""}`).join(", ")})
                </span>
              )}
            </Pill>
          )}
          {/* Non-English */}
          {ingest.non_english_rows > 0 && (
            <Pill icon={Languages} color="blue">
              <strong>{ingest.non_english_rows} non-English row{ingest.non_english_rows !== 1 ? "s" : ""}</strong>
              {" — "}
              {Object.entries(ingest.language_distribution)
                .filter(([l]) => l !== "en" && l !== "unknown")
                .map(([l, n]) => `${n}× ${langName(l)}`).join(", ")}
              <span className="block text-2xs mt-0.5 opacity-75">Translated automatically before labeling</span>
            </Pill>
          )}
          {ingest.pii_redactions === 0 && ingest.non_english_rows === 0 && (
            <p className="text-xs text-muted-foreground">No PII detected · all rows in English</p>
          )}
          {ingest.column_warnings && ingest.column_warnings.length > 0 && (
            <div className="mt-3 space-y-1.5">
              {ingest.column_warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                  <AlertCircle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-800">{w}</p>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* Stage 2 — Taxonomy */}
      {discovery && (
        <Section icon={Sparkles} title="Taxonomy confirmed" done>
          <p className="text-xs text-muted-foreground mb-2">
            {discovery.created_by === "discovery" ? "AI-suggested" : discovery.created_by === "imported" ? "Imported from previous run" : "Manually defined"} · {discovery.category_count} categories · version {discovery.version}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {discovery.categories.map((c) => (
              <div key={c.key} className="rounded-lg border border-border bg-secondary/50 px-2.5 py-1.5 text-xs">
                <span className="font-mono text-muted-foreground">{c.key}</span>
                <span className="font-medium ml-1.5">{c.label}</span>
              </div>
            ))}
            <div className="rounded-lg border border-dashed border-border px-2.5 py-1.5 text-xs text-muted-foreground">
              <span className="font-mono">other</span>
              <span className="ml-1.5 opacity-75">auto</span>
            </div>
          </div>
        </Section>
      )}

      {/* Stage 3 — AI labeling */}
      {extraction && (
        <Section icon={Brain} title="AI labeling" done>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <Stat label="Total labeled" value={extraction.processed} />
            <Stat label="Auto-confirmed" value={extraction.auto_confirmed} />
            <Stat label="Sent to review" value={extraction.flagged} accent={extraction.flagged > 0} />
          </div>

          {/* Model + cost inline */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground mb-3">
            {extraction.model && (
              <span className="flex items-center gap-1">
                <Brain className="h-3 w-3" />
                <span className="font-mono">{extraction.model}</span>
              </span>
            )}
            {extraction.actual_cost_usd != null && (
              <span>${extraction.actual_cost_usd.toFixed(4)} spent</span>
            )}
          </div>

          {/* Why items were flagged */}
          {Object.keys(extraction.flag_breakdown).length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
                <Flag className="h-3 w-3" /> Why items went to review
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(extraction.flag_breakdown)
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
          {/* Low-confidence category warnings */}
          {extraction.low_confidence_categories && extraction.low_confidence_categories.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 mt-1">
              <AlertCircle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-800">
                <strong>Low model confidence</strong> on:{" "}
                {extraction.low_confidence_categories.map((c) => (
                  <span key={c} className="font-mono bg-amber-100 rounded px-1 mr-1">{c}</span>
                ))}
                — consider reviewing more items in these categories.
              </p>
            </div>
          )}
        </Section>
      )}

      {/* Stage 4 — Human review CTA */}
      {review ? (
        review.pending > 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-900">
                  {review.pending} item{review.pending !== 1 ? "s" : ""} need your review
                </p>
                <p className="text-xs text-amber-700 mt-0.5">
                  {review.reviewed} of {review.total_flagged} reviewed · {review.pct_complete}% complete
                </p>
              </div>
            </div>
            <Button size="sm" onClick={() => navigate(`/run/${runId}/review`)} className="shrink-0">
              Review queue <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <div className="rounded-xl border border-green-200 bg-green-50 p-4 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-green-900">All items reviewed</p>
              <p className="text-xs text-green-700 mt-0.5">{review.total_flagged} flagged items confirmed by a human</p>
            </div>
          </div>
        )
      ) : null}

      {/* AI Summary */}
      <Section icon={FileText} title="AI Summary" done={!!run.ai_summary}>
        {run.ai_summary ? (
          <div className="space-y-3">
            <p className="text-sm text-foreground/90 whitespace-pre-wrap leading-relaxed">
              {run.ai_summary}
            </p>
            <button
              onClick={() => summaryMutation.mutate()}
              disabled={summaryMutation.isPending}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {summaryMutation.isPending ? "Regenerating…" : "Regenerate"}
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm text-muted-foreground">
              Generate a 3-paragraph executive summary of this run using the labeled data.
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => summaryMutation.mutate()}
              disabled={summaryMutation.isPending}
            >
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              {summaryMutation.isPending ? "Generating…" : "Generate summary"}
            </Button>
            {summaryMutation.isError && (
              <p className="text-xs text-destructive">{(summaryMutation.error as Error).message}</p>
            )}
          </div>
        )}
      </Section>

    </div>
  );
}

// ─── Insights tab ─────────────────────────────────────────────────────────────

function InsightsTab({ runId }: { runId: string }) {
  const navigate = useNavigate();

  const { data: signals, isLoading } = useQuery({
    queryKey: ["attention", runId],
    queryFn: () => getAttentionSignals(runId),
  });

  if (isLoading) return <TabSpinner />;
  if (!signals) return null;

  return (
    <div className="space-y-8">

      {signals.briefing && (
        <p className="text-sm text-muted-foreground leading-relaxed">{signals.briefing}</p>
      )}

      {signals.attention.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">Needs attention</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {signals.attention.map((card, i) => (
              <InsightsAttentionCard
                key={i}
                card={card}
                onAction={card.action === "refine_taxonomy" ? () => navigate(`/run/${runId}/discovery`) : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {signals.category_table.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">Category breakdown</p>
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-secondary/40">
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Category</th>
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Volume</th>
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Sentiment</th>
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">High urgency</th>
                    <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Top signal</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.category_table.map((row) => (
                    <InsightsCategoryRow key={row.category} row={row} total={signals.total_labeled} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {Object.keys(signals.verbatim).length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">What they said</p>
          <div className="space-y-4">
            {Object.entries(signals.verbatim)
              .filter(([, quotes]) => quotes.length > 0)
              .map(([cat, quotes]) => (
                <div key={cat}>
                  <p className="text-xs font-mono text-muted-foreground mb-1.5">{cat}</p>
                  <div className="space-y-1.5">
                    {quotes.map((q, i) => (
                      <blockquote key={i} className="text-xs text-foreground bg-secondary/40 border-l-2 border-border px-3 py-2 rounded-r leading-relaxed">
                        "{q}"
                      </blockquote>
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

    </div>
  );
}

function InsightsAttentionCard({
  card,
  onAction,
}: {
  card: AttentionCardData;
  onAction?: () => void;
}) {
  const borderColor = card.severity === "high" ? "border-l-red-500" : "border-l-orange-400";
  const dotColor   = card.severity === "high" ? "bg-red-500"     : "bg-orange-400";
  return (
    <Card className={cn("overflow-hidden border-l-4", borderColor)}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full flex-shrink-0 mt-0.5", dotColor)} />
            <p className="text-sm font-semibold capitalize">{card.title}</p>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground font-medium">{card.count}</span>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed ml-4 mb-3">{card.detail}</p>
        {onAction && (
          <button onClick={onAction} className="ml-4 text-xs text-primary hover:underline font-medium">
            Refine taxonomy →
          </button>
        )}
      </CardContent>
    </Card>
  );
}

function InsightsCategoryRow({ row, total }: { row: CategoryRow; total: number }) {
  const isOther = row.category === "other";
  const pct = Math.round((row.count / (total || 1)) * 100);
  const sentTotal = (row.positive + row.negative + row.neutral) || 1;
  const negW = Math.round((row.negative / sentTotal) * 100);
  const posW = Math.round((row.positive / sentTotal) * 100);
  const neuW = Math.round((row.neutral  / sentTotal) * 100);
  return (
    <tr className={cn("border-b last:border-0 hover:bg-secondary/30 transition-colors", isOther && "opacity-60")}>
      <td className="px-4 py-2.5">
        <Badge variant="secondary" className="font-mono text-xs">{row.category}</Badge>
      </td>
      <td className="px-4 py-2.5">
        <span className="tabular-nums text-foreground font-medium">{row.count}</span>
        <span className="text-muted-foreground text-2xs ml-1">({pct}%)</span>
      </td>
      <td className="px-4 py-2.5">
        <div className="flex h-1.5 w-20 rounded-full overflow-hidden gap-px mb-0.5">
          {negW > 0 && <div className="bg-red-400 h-full" style={{ width: `${negW}%` }} />}
          {posW > 0 && <div className="bg-green-500 h-full" style={{ width: `${posW}%` }} />}
          {neuW > 0 && <div className="bg-gray-300 h-full" style={{ width: `${neuW}%` }} />}
        </div>
        <div className="flex gap-2">
          <span className="text-2xs text-red-500">−{row.negative}</span>
          <span className="text-2xs text-green-600">+{row.positive}</span>
          <span className="text-2xs text-muted-foreground">~{row.neutral}</span>
        </div>
      </td>
      <td className="px-4 py-2.5">
        {row.high_urgency > 0
          ? <span className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded px-1.5 py-0.5">{row.high_urgency} high</span>
          : <span className="text-2xs text-muted-foreground">—</span>}
      </td>
      <td className="px-4 py-2.5 max-w-[180px]">
        {row.top_phrase
          ? <span className="text-xs text-muted-foreground italic truncate block">"{row.top_phrase}"</span>
          : <span className="text-2xs text-muted-foreground">—</span>}
      </td>
    </tr>
  );
}

// ─── Data tab ─────────────────────────────────────────────────────────────────

const DATA_PAGE_SIZE = 50;
const SENTIMENTS = ["positive", "negative", "neutral", "mixed"] as const;
const URGENCIES  = ["high", "medium", "low"] as const;

function DataTab({ runId }: { runId: string }) {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [urgencyFilter, setUrgencyFilter] = useState("");

  // Debounce search input 300 ms
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset to page 0 whenever any filter changes
  useEffect(() => { setPage(0); }, [debouncedSearch, categoryFilter, sentimentFilter, urgencyFilter]);

  const filters: LabelFilters = {
    search:    debouncedSearch || undefined,
    category:  categoryFilter  || undefined,
    sentiment: sentimentFilter || undefined,
    urgency:   urgencyFilter   || undefined,
  };
  const hasFilters = Object.values(filters).some(Boolean);

  const { data, isLoading } = useQuery({
    queryKey: ["labels", runId, page, filters],
    queryFn: () => getLabels(runId, page, DATA_PAGE_SIZE, filters),
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories", runId],
    queryFn: () => getEnumCategories(runId),
    select: (cats) => cats.map((c) => c.key),
  });

  const totalPages = data ? Math.ceil(data.total / DATA_PAGE_SIZE) : 1;

  return (
    <div>
      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {/* Search */}
        <div className="relative flex-1 min-w-[180px]">
          <input
            type="text"
            placeholder="Search feedback…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-8 rounded-md border border-input bg-card pl-3 pr-8 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              ×
            </button>
          )}
        </div>

        {/* Category */}
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="h-8 rounded-md border border-input bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
        >
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        {/* Sentiment */}
        <select
          value={sentimentFilter}
          onChange={(e) => setSentimentFilter(e.target.value)}
          className="h-8 rounded-md border border-input bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
        >
          <option value="">All sentiments</option>
          {SENTIMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Urgency */}
        <select
          value={urgencyFilter}
          onChange={(e) => setUrgencyFilter(e.target.value)}
          className="h-8 rounded-md border border-input bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
        >
          <option value="">All urgencies</option>
          {URGENCIES.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-muted-foreground"
            onClick={() => { setSearch(""); setCategoryFilter(""); setSentimentFilter(""); setUrgencyFilter(""); }}
          >
            Clear filters
          </Button>
        )}

        <div className="ml-auto flex items-center gap-3">
          {data && (
            <p className="text-xs text-muted-foreground whitespace-nowrap">
              {data.total.toLocaleString()} {hasFilters ? "matching" : "total"} items
            </p>
          )}
          <Button variant="outline" size="sm" onClick={() => window.open(csvExportUrl(runId))}>
            Export CSV
          </Button>
        </div>
      </div>

      {isLoading && <TabSpinner />}

      {!isLoading && data && data.total === 0 && (
        <p className="text-sm text-muted-foreground py-8 text-center">
          {hasFilters ? "No items match the current filters." : "No labeled items yet."}
        </p>
      )}

      {!isLoading && data && data.total > 0 && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-secondary/40">
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground w-[40%]">Feedback</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Category</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Sentiment</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Urgency</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Conf.</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Source</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => <DataRow key={item.id} item={item} />)}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 px-4 py-3 border-t">
              <Button variant="outline" size="icon" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-xs text-muted-foreground tabular-nums">{page + 1} / {totalPages}</span>
              <Button variant="outline" size="icon" onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function DataRow({ item }: { item: LabeledItem }) {
  return (
    <tr className="border-b last:border-0 hover:bg-secondary/30 transition-colors">
      <td className="px-4 py-2.5 max-w-[300px]">
        <p className="line-clamp-2 leading-relaxed text-foreground">{item.text}</p>
        {item.key_phrase && <p className="text-2xs text-muted-foreground mt-0.5 truncate">"{item.key_phrase}"</p>}
        <div className="flex gap-1 mt-1 flex-wrap">
          {item.source_channel && (
            <span className="text-2xs text-muted-foreground bg-secondary rounded px-1">{item.source_channel}</span>
          )}
          {item.language && item.language !== "en" && (
            <span className="text-2xs text-blue-600 bg-blue-50 rounded px-1">{item.language}</span>
          )}
          {item.review_flags.length > 0 && (
            <span className="text-2xs text-amber-700 bg-amber-50 rounded px-1">reviewed</span>
          )}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <Badge variant="secondary" className="font-mono text-xs">{item.category}</Badge>
      </td>
      <td className="px-4 py-2.5">
        <Badge variant="outline" className={cn("text-xs", SENTIMENT_BADGE[item.sentiment] ?? "")}>
          {item.sentiment}
        </Badge>
      </td>
      <td className="px-4 py-2.5">
        <Badge variant="outline" className={cn("text-xs", URGENCY_BADGE[item.urgency] ?? "")}>
          {item.urgency}
        </Badge>
      </td>
      <td className="px-4 py-2.5 tabular-nums text-muted-foreground">{Math.round(item.confidence * 100)}%</td>
      <td className="px-4 py-2.5">
        <span className={cn(
          "text-2xs font-medium rounded px-1.5 py-0.5",
          item.source === "human" ? "bg-green-50 text-green-700" : "bg-secondary text-muted-foreground",
        )}>
          {item.source === "human" ? "Human" : "AI"}
        </span>
      </td>
    </tr>
  );
}

// ─── Small shared components ──────────────────────────────────────────────────

function Section({ icon: Icon, title, done, children }: {
  icon: React.ElementType; title: string; done?: boolean; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        {done
          ? <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
          : <Circle className="h-4 w-4 text-muted-foreground shrink-0" />}
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold">{title}</span>
      </div>
      <Card>
        <CardContent className="p-4">{children}</CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, muted, accent }: { label: string; value: number | string; muted?: boolean; accent?: boolean }) {
  return (
    <div className="rounded-lg bg-secondary/60 px-3 py-2">
      <p className={cn("text-base font-bold tabular-nums", muted && "text-muted-foreground", accent && "text-amber-600")}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
      <p className="text-2xs text-muted-foreground">{label}</p>
    </div>
  );
}

function Pill({ icon: Icon, color, children }: { icon: React.ElementType; color: "yellow" | "blue"; children: React.ReactNode }) {
  const s = { yellow: "bg-yellow-50 border-yellow-200 text-yellow-800", blue: "bg-blue-50 border-blue-200 text-blue-800" };
  const i = { yellow: "text-yellow-600", blue: "text-blue-600" };
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-xs mt-2", s[color])}>
      <Icon className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", i[color])} />
      <div>{children}</div>
    </div>
  );
}

function TabSpinner() {
  return (
    <div className="flex justify-center pt-12">
      <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

// ─── Quality tab ─────────────────────────────────────────────────────────────

function AgreementBar({ value, label }: { value: number; label: string }) {
  const pct = Math.round(value * 100);
  const color = pct >= 90 ? "bg-green-500" : pct >= 75 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn("font-semibold tabular-nums", pct >= 90 ? "text-green-700" : pct >= 75 ? "text-yellow-700" : "text-red-600")}>
          {pct}%
        </span>
      </div>
      <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function QualityTab({ runId }: { runId: string }) {
  const { data: report, isLoading, refetch } = useQuery({
    queryKey: ["calibration", runId],
    queryFn: () => getCalibration(runId),
  });

  const calibrateMutation = useMutation({
    mutationFn: () => runCalibration(runId),
    onSuccess: () => refetch(),
  });

  if (isLoading) return <TabSpinner />;
  if (!report) return null;

  const hasHumanData = report.total_reviewed > 0;
  const humanAccPct = report.human_accuracy != null ? Math.round(report.human_accuracy * 100) : null;

  return (
    <div className="max-w-2xl space-y-5">

      {/* ── Human Review Accuracy ── */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Human review accuracy
            </p>
            {hasHumanData && (
              <span className={cn(
                "text-xs font-semibold rounded-full px-2.5 py-1 border",
                humanAccPct! >= 90 ? "bg-green-50 text-green-700 border-green-200" :
                humanAccPct! >= 75 ? "bg-yellow-50 text-yellow-700 border-yellow-200" :
                "bg-red-50 text-red-700 border-red-200",
              )}>
                {humanAccPct}% confirmed
              </span>
            )}
          </div>

          {!hasHumanData ? (
            <div className="text-center py-4">
              <p className="text-sm text-muted-foreground">No reviewed items yet.</p>
              <p className="text-xs text-muted-foreground mt-1">
                Review flagged items in the review queue to see human accuracy stats here.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Summary row */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg bg-secondary/60 px-3 py-2 text-center">
                  <p className="text-base font-bold tabular-nums">{report.total_reviewed}</p>
                  <p className="text-2xs text-muted-foreground">Total reviewed</p>
                </div>
                <div className="rounded-lg bg-green-50 border border-green-100 px-3 py-2 text-center">
                  <p className="text-base font-bold tabular-nums text-green-700">
                    {report.per_category_human.reduce((s, c) => s + c.confirmed, 0)}
                  </p>
                  <p className="text-2xs text-green-600">Confirmed</p>
                </div>
                <div className="rounded-lg bg-orange-50 border border-orange-100 px-3 py-2 text-center">
                  <p className="text-base font-bold tabular-nums text-orange-700">
                    {report.per_category_human.reduce((s, c) => s + c.corrected, 0)}
                  </p>
                  <p className="text-2xs text-orange-600">Corrected</p>
                </div>
              </div>

              {/* Per-category */}
              {report.per_category_human.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2">By category</p>
                  <div className="space-y-2">
                    {report.per_category_human.map((cat) => {
                      const pct = Math.round(cat.accuracy * 100);
                      const barColor = pct >= 90 ? "bg-green-400" : pct >= 75 ? "bg-yellow-400" : "bg-red-400";
                      return (
                        <div key={cat.category}>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-mono text-muted-foreground">{cat.category}</span>
                            <span className="tabular-nums text-muted-foreground">
                              {cat.confirmed}/{cat.reviewed} confirmed
                              <span className="ml-2 font-semibold text-foreground">{pct}%</span>
                            </span>
                          </div>
                          <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                            <div className={cn("h-full rounded-full transition-all", barColor)} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Self-Consistency ── */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Self-consistency check
              </p>
              {report.calibrated_at && (
                <p className="text-2xs text-muted-foreground mt-0.5">
                  Last run {new Date(report.calibrated_at).toLocaleString()}
                </p>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => calibrateMutation.mutate()}
              disabled={calibrateMutation.isPending}
            >
              {calibrateMutation.isPending ? (
                <span className="flex items-center gap-1.5">
                  <span className="h-3.5 w-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  Running…
                </span>
              ) : report.has_self_check ? "Re-run" : "Run calibration"}
            </Button>
          </div>

          {calibrateMutation.isError && (
            <p className="text-xs text-destructive mb-3">
              {(calibrateMutation.error as Error).message}
            </p>
          )}

          {!report.has_self_check && !calibrateMutation.isPending ? (
            <div className="rounded-lg bg-secondary/50 border border-dashed border-border p-4 text-center">
              <p className="text-sm font-medium mb-1">Not yet run</p>
              <p className="text-xs text-muted-foreground max-w-xs mx-auto">
                Re-labels {20} random items and compares to the original AI labels.
                Reveals which categories the model is most reproducible on.
              </p>
            </div>
          ) : report.has_self_check ? (
            <div className="space-y-4">
              {/* Agreement scores */}
              <div className="space-y-3">
                <AgreementBar value={report.category_agreement!} label={`Category agreement (${report.sample_size} items sampled)`} />
                <AgreementBar value={report.sentiment_agreement!} label="Sentiment agreement" />
                <AgreementBar value={report.urgency_agreement!} label="Urgency agreement" />
              </div>

              {/* Per-category consistency */}
              {report.per_category_consistency.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2">By category</p>
                  <div className="space-y-2">
                    {report.per_category_consistency.map((cat) => {
                      const pct = Math.round(cat.agreement * 100);
                      const barColor = pct >= 90 ? "bg-green-400" : pct >= 75 ? "bg-yellow-400" : "bg-red-400";
                      return (
                        <div key={cat.category}>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-mono text-muted-foreground">{cat.category}</span>
                            <span className="tabular-nums text-muted-foreground">
                              {cat.matches}/{cat.total}
                              <span className="ml-2 font-semibold text-foreground">{pct}%</span>
                            </span>
                          </div>
                          <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                            <div className={cn("h-full rounded-full transition-all", barColor)} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ── Confusion Matrix ── */}
      {report.confusion_pairs.length > 0 && (
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
              Correction patterns
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              Categories the AI mislabeled — showing what humans corrected them to.
            </p>
            <div className="space-y-2">
              {report.confusion_pairs.map((pair) => (
                <div key={`${pair.from_cat}→${pair.to_cat}`} className="flex items-center gap-2 text-xs">
                  <span className="font-mono bg-red-50 text-red-700 border border-red-200 rounded px-1.5 py-0.5 shrink-0">
                    {pair.from_cat}
                  </span>
                  <span className="text-muted-foreground">→</span>
                  <span className="font-mono bg-green-50 text-green-700 border border-green-200 rounded px-1.5 py-0.5 shrink-0">
                    {pair.to_cat}
                  </span>
                  <span className="ml-auto tabular-nums text-muted-foreground font-medium">
                    {pair.count}×
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Confidence Calibration Curve ── */}
      {hasHumanData && report.confidence_buckets.some((b) => b.count > 0) && (
        <Card>
          <CardContent className="p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
              Confidence calibration
            </p>
            <p className="text-xs text-muted-foreground mb-4">
              Does higher confidence actually mean higher accuracy? A well-calibrated model scores closer to the diagonal.
            </p>
            <div className="space-y-3">
              {report.confidence_buckets.map((bucket) => {
                if (bucket.count === 0) return null;
                const pct = bucket.accuracy != null ? Math.round(bucket.accuracy * 100) : null;
                const barColor = pct == null ? "bg-secondary" : pct >= 90 ? "bg-green-500" : pct >= 75 ? "bg-yellow-400" : "bg-red-400";
                return (
                  <div key={bucket.label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-muted-foreground">
                        Confidence {bucket.label}
                        <span className="ml-1.5 text-2xs opacity-60">({bucket.count} items)</span>
                      </span>
                      <span className={cn(
                        "font-semibold tabular-nums",
                        pct == null ? "text-muted-foreground" :
                        pct >= 90 ? "text-green-700" : pct >= 75 ? "text-yellow-700" : "text-red-600"
                      )}>
                        {pct != null ? `${pct}% accurate` : "—"}
                      </span>
                    </div>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all duration-500", barColor)}
                        style={{ width: pct != null ? `${pct}%` : "0%" }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

    </div>
  );
}

// ─── Ask AI tab ───────────────────────────────────────────────────────────────

const SUGGESTED_QUESTIONS = [
  "What are users complaining about most?",
  "What features are users requesting?",
  "What's driving negative sentiment?",
  "Which issues are most urgent?",
  "Summarize the overall feedback",
] as const;

const CONFIDENCE_STYLE = {
  high:   { label: "High confidence",   cls: "bg-green-50 text-green-700 border-green-200" },
  medium: { label: "Medium confidence", cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
  low:    { label: "Low confidence",    cls: "bg-gray-100 text-muted-foreground border-border" },
} as const;

interface HistoryEntry {
  id: string;
  question: string;
  answer: QueryAnswer;
}

function AskTab({ runId }: { runId: string }) {
  const [question, setQuestion] = useState("");
  // sessionId persists per page mount; null = will be assigned by server on first ask
  const [sessionId, setSessionId] = useState<string | null>(null);
  // local entries for the current session, newest first
  const [localEntries, setLocalEntries] = useState<HistoryEntry[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Load persisted history on mount
  const { data: historyData = [] } = useQuery({
    queryKey: ["queryHistory", runId],
    queryFn: () => getQueryHistory(runId),
  });

  // Seed the current session from the most-recent persisted session (once, on first load)
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (!seeded && historyData.length > 0 && localEntries.length === 0) {
      const latest = historyData[0]; // newest session first
      setSessionId(latest.session_id);
      const entries: HistoryEntry[] = latest.messages
        .slice()
        .reverse() // newest first for display
        .map((m) => ({
          id: m.id,
          question: m.question,
          answer: {
            answer: m.answer,
            key_insights: m.key_insights,
            sources: m.sources as QueryAnswer["sources"],
            confidence: m.confidence as QueryAnswer["confidence"],
          },
        }));
      setLocalEntries(entries);
      setSeeded(true);
    }
  }, [historyData, seeded, localEntries.length]);

  const mutation = useMutation({
    mutationFn: (q: string) => askQuestion(runId, q, sessionId ?? undefined),
    onSuccess: (resp, q) => {
      // If this was the first question, remember the server-assigned session id
      if (!sessionId) setSessionId(resp.session_id);
      const entry: HistoryEntry = {
        id: `${Date.now()}`,
        question: q,
        answer: resp.answer,
      };
      setLocalEntries((prev) => [entry, ...prev]);
      setExpandedIds(new Set());
      setQuestion("");
    },
  });

  const submit = () => {
    const q = question.trim();
    if (!q || mutation.isPending) return;
    mutation.mutate(q);
  };

  const newConversation = () => {
    setSessionId(null);
    setLocalEntries([]);
    setExpandedIds(new Set());
  };

  const latest = localEntries[0] ?? null;
  const older = localEntries.slice(1);

  // Past sessions (not the current one) for the history sidebar
  const pastSessions = historyData.filter((s) => s.session_id !== sessionId);

  return (
    <div className="max-w-2xl space-y-5">

      {/* ── Input card ── */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Ask a question about this feedback
            </p>
            {localEntries.length > 0 && (
              <button
                onClick={newConversation}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                + New conversation
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g. What are users complaining about most?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              disabled={mutation.isPending}
              className="flex-1 h-9 rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
            />
            <Button
              onClick={submit}
              disabled={!question.trim() || mutation.isPending}
              className="shrink-0 w-9 p-0"
            >
              {mutation.isPending
                ? <span className="h-4 w-4 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
                : <Send className="h-4 w-4" />}
            </Button>
          </div>

          {/* Suggested questions — shown when no history yet */}
          {localEntries.length === 0 && !mutation.isPending && (
            <div className="mt-3">
              <p className="text-2xs text-muted-foreground mb-2">Try asking:</p>
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTED_QUESTIONS.map((sq) => (
                  <button
                    key={sq}
                    onClick={() => setQuestion(sq)}
                    className="text-xs text-muted-foreground bg-secondary hover:bg-secondary/70 border border-border rounded-full px-3 py-1 transition-colors"
                  >
                    {sq}
                  </button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Loading ── */}
      {mutation.isPending && (
        <div className="flex items-center gap-3 py-2 text-sm text-muted-foreground">
          <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0" />
          Analyzing feedback…
        </div>
      )}

      {/* ── Error ── */}
      {mutation.isError && (
        <p className="text-sm text-destructive px-1">
          {(mutation.error as Error).message}
        </p>
      )}

      {/* ── Latest answer ── */}
      {latest && !mutation.isPending && (
        <AnswerBlock entry={latest} />
      )}

      {/* ── Earlier in this session ── */}
      {older.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Earlier in this conversation
          </p>
          <div className="space-y-1">
            {older.map((entry) => {
              const open = expandedIds.has(entry.id);
              return (
                <div key={entry.id} className="rounded-lg border border-border overflow-hidden">
                  <button
                    onClick={() => setExpandedIds((prev) => {
                      const next = new Set(prev);
                      open ? next.delete(entry.id) : next.add(entry.id);
                      return next;
                    })}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left hover:bg-secondary/50 transition-colors"
                  >
                    <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="flex-1 text-muted-foreground">{entry.question}</span>
                    <ChevronRight className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform shrink-0", open && "rotate-90")} />
                  </button>
                  {open && (
                    <div className="px-4 pb-4 border-t border-border bg-secondary/20">
                      <AnswerBlock entry={entry} compact />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Past sessions ── */}
      {pastSessions.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Past conversations
          </p>
          <div className="space-y-1">
            {pastSessions.map((s) => {
              const open = expandedIds.has(s.session_id);
              const firstQ = s.messages[0]?.question ?? "Conversation";
              return (
                <div key={s.session_id} className="rounded-lg border border-border overflow-hidden">
                  <button
                    onClick={() => setExpandedIds((prev) => {
                      const next = new Set(prev);
                      open ? next.delete(s.session_id) : next.add(s.session_id);
                      return next;
                    })}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left hover:bg-secondary/50 transition-colors"
                  >
                    <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <span className="flex-1 text-muted-foreground truncate">{firstQ}</span>
                    <span className="text-2xs text-muted-foreground shrink-0 mr-1">
                      {s.messages.length} Q{s.messages.length !== 1 ? "s" : ""}
                    </span>
                    <ChevronRight className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform shrink-0", open && "rotate-90")} />
                  </button>
                  {open && (
                    <div className="px-4 pb-4 border-t border-border bg-secondary/20 space-y-3 pt-3">
                      {s.messages.slice().reverse().map((m) => (
                        <AnswerBlock
                          key={m.id}
                          entry={{
                            id: m.id,
                            question: m.question,
                            answer: {
                              answer: m.answer,
                              key_insights: m.key_insights,
                              sources: m.sources as QueryAnswer["sources"],
                              confidence: m.confidence as QueryAnswer["confidence"],
                            },
                          }}
                          compact
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function AnswerBlock({ entry, compact }: { entry: HistoryEntry; compact?: boolean }) {
  const { answer } = entry;
  const conf = CONFIDENCE_STYLE[answer.confidence];
  const [sourcesOpen, setSourcesOpen] = useState(!compact);

  return (
    <div className={cn("space-y-4", compact && "pt-3")}>

      {/* Answer + confidence */}
      <Card className={cn(!compact && "border-primary/20")}>
        <CardContent className="p-5 space-y-4">
          <div className="flex items-start gap-3">
            <p className="text-sm leading-relaxed flex-1">{answer.answer}</p>
            <span className={cn("text-2xs font-medium rounded-full px-2.5 py-1 border shrink-0 whitespace-nowrap", conf.cls)}>
              {conf.label}
            </span>
          </div>

          {/* Key insights */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              Key insights
            </p>
            <ul className="space-y-1.5">
              {answer.key_insights.map((insight, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />
                  {insight}
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>

      {/* Sources toggle */}
      <div>
        <button
          onClick={() => setSourcesOpen((v) => !v)}
          className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground mb-2 transition-colors"
        >
          <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", sourcesOpen && "rotate-90")} />
          Supporting quotes ({answer.sources.length})
        </button>
        {sourcesOpen && (
          <div className="space-y-2">
            {answer.sources.map((src, i) => (
              <SourceCard key={i} source={src} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SourceCard({ source }: { source: QuerySource }) {
  return (
    <div className="rounded-lg border border-border bg-secondary/30 px-4 py-3 space-y-2">
      <p className="text-sm leading-relaxed">"{source.text}"</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" className="font-mono text-xs">{source.category}</Badge>
        <Badge variant="outline" className={cn("text-xs", SENTIMENT_BADGE[source.sentiment] ?? "")}>
          {source.sentiment}
        </Badge>
        <Badge variant="outline" className={cn("text-xs", URGENCY_BADGE[source.urgency] ?? "")}>
          {source.urgency}
        </Badge>
      </div>
      <p className="text-2xs text-muted-foreground italic">{source.why_relevant}</p>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");

  const { data: run, isLoading } = useQuery({
    queryKey: ["run", rid],
    queryFn: () => getRun(rid),
  });

  // Prefetch pipeline for overview (needed to know review pending count for tab badge)
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", rid],
    queryFn: () => getPipeline(rid),
    enabled: !!rid,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center pt-24">
        <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!run) return null;

  const statusMeta = STATUS_LABEL[run.status] ?? { label: run.status, dot: "bg-gray-400" };
  const reviewPending = pipeline?.review?.pending ?? 0;
  const isComplete = run.status === "complete";

  return (
    <div>
      <PageHeader
        title={run.filename}
        subtitle={`${run.total_rows > 0 ? `${run.total_rows.toLocaleString()} rows · ` : ""}${statusMeta.label}`}
        breadcrumb={[{ label: "Runs", href: "/" }]}
        action={
          isComplete ? (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => navigate(`/run/${rid}/review`)}>
                Review queue
                {reviewPending > 0 && (
                  <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] px-1 rounded-full bg-amber-500 text-white text-2xs font-bold">
                    {reviewPending}
                  </span>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={() => window.open(csvExportUrl(rid))}>
                Export CSV
              </Button>
            </div>
          ) : null
        }
      />

      {isComplete ? (
        <>
          <TabBar active={tab} onChange={setTab} reviewPending={reviewPending} />
          {tab === "overview" && <OverviewTab runId={rid} run={run} navigate={navigate} />}
          {tab === "insights" && <InsightsTab runId={rid} />}
          {tab === "data"     && <DataTab runId={rid} />}
          {tab === "ask"      && <AskTab runId={rid} />}
          {tab === "quality"  && <QualityTab runId={rid} />}
        </>
      ) : (
        /* Run not complete — show a simple status card */
        <Card className="max-w-md">
          <CardContent className="p-6 flex items-center gap-4">
            <div className={cn("h-3 w-3 rounded-full shrink-0", statusMeta.dot)} />
            <div>
              <p className="font-medium text-sm">{statusMeta.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {run.status === "extracting"
                  ? `${run.processed_rows} of ${run.total_rows} items labeled`
                  : "This run is still in progress."}
              </p>
            </div>
            {run.status === "extracting" && (
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => navigate(`/run/${rid}/extract`)}>
                View progress
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
