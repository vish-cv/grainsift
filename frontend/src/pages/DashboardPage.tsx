import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, GitBranch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import {
  getAttentionSignals,
  getTimeseries,
  csvExportUrl,
  type AttentionCard,
  type CategoryRow,
} from "@/api/dashboard";
import { getLabels, type LabeledItem } from "@/api/pipeline";
import { cn } from "@/lib/utils";

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

const SEVERITY_BORDER: Record<string, string> = {
  high:   "border-l-4 border-l-red-500",
  medium: "border-l-4 border-l-orange-400",
};

const SEVERITY_DOT: Record<string, string> = {
  high:   "bg-red-500",
  medium: "bg-orange-400",
};

const LABELS_PAGE_SIZE = 50;

export function DashboardPage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();
  const [labelsPage, setLabelsPage] = useState(0);

  const { data: signals, isLoading, error } = useQuery({
    queryKey: ["attention", rid],
    queryFn: () => getAttentionSignals(rid),
    enabled: !!rid,
  });

  const { data: timeseries } = useQuery({
    queryKey: ["timeseries", rid],
    queryFn: () => getTimeseries(rid),
    enabled: !!rid,
  });

  const { data: labelsData } = useQuery({
    queryKey: ["labels", rid, labelsPage],
    queryFn: () => getLabels(rid, labelsPage, LABELS_PAGE_SIZE),
    enabled: !!rid,
  });

  if (isLoading) return <Spinner />;
  if (error) return <p className="text-destructive text-sm">{(error as Error).message}</p>;
  if (!signals) return null;

  const totalLabelPages = labelsData ? Math.ceil(labelsData.total / LABELS_PAGE_SIZE) : 1;
  const maxDay = timeseries ? Math.max(...timeseries.map((d) => d.total), 1) : 1;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={`${signals.total_labeled.toLocaleString()} labeled items`}
        breadcrumb={[{ label: "Runs", href: "/" }]}
        action={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate(`/run/${rid}/pipeline`)}>
              <GitBranch className="mr-1.5 h-3.5 w-3.5" />
              Pipeline
            </Button>
            <Button variant="outline" size="sm" onClick={() => navigate(`/run/${rid}/review`)}>
              Review queue
            </Button>
            <Button variant="outline" size="sm" onClick={() => window.open(csvExportUrl(rid))}>
              Export CSV
            </Button>
          </div>
        }
      />

      {/* ── Briefing line ── */}
      {signals.briefing && (
        <p className="text-sm text-muted-foreground mb-6 leading-relaxed">
          {signals.briefing}
        </p>
      )}

      {/* ── Attention cards ── */}
      {signals.attention.length > 0 && (
        <div className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Needs attention
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {signals.attention.map((card, i) => (
              <AttentionCardView
                key={i}
                card={card}
                onAction={() =>
                  card.action === "refine_taxonomy"
                    ? navigate(`/run/${rid}/pipeline`)
                    : navigate(`/run/${rid}/review`)
                }
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Category breakdown (unified table) ── */}
      {signals.category_table.length > 0 && (
        <div className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Category breakdown
          </p>
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
                    <CategoryTableRow
                      key={row.category}
                      row={row}
                      total={signals.total_labeled}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {/* ── Trend (below the fold) ── */}
      {timeseries && timeseries.length > 0 && (
        <div className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            Feedback volume over time
          </p>
          <Card>
            <CardContent className="p-5">
              <div className="overflow-x-auto">
                <div className="flex items-end gap-1 h-24 min-w-max">
                  {timeseries.map((point) => {
                    const barH = Math.round((point.total / maxDay) * 88);
                    return (
                      <div key={point.date} className="flex flex-col items-center gap-1 group">
                        <div
                          className="w-5 bg-primary/50 group-hover:bg-primary rounded-sm transition-colors cursor-default"
                          style={{ height: `${barH}px` }}
                          title={`${point.date}: ${point.total} items`}
                        />
                        <span className="text-2xs text-muted-foreground tabular-nums" style={{ fontSize: "9px" }}>
                          {point.date.slice(5)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Verbatim quotes ── */}
      {Object.keys(signals.verbatim).length > 0 && (
        <div className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
            What they said
          </p>
          <div className="space-y-4">
            {Object.entries(signals.verbatim)
              .filter(([, quotes]) => quotes.length > 0)
              .map(([cat, quotes]) => (
                <div key={cat}>
                  <p className="text-xs font-mono text-muted-foreground mb-1.5">{cat}</p>
                  <div className="space-y-1.5">
                    {quotes.map((q, i) => (
                      <blockquote
                        key={i}
                        className="text-xs text-foreground bg-secondary/40 border-l-2 border-border px-3 py-2 rounded-r leading-relaxed"
                      >
                        "{q}"
                      </blockquote>
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* ── Labeled items table ── */}
      {labelsData && labelsData.total > 0 && (
        <div className="mt-2">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">All items</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {labelsData.total.toLocaleString()} total · sorted by urgency
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => window.open(csvExportUrl(rid))}>
              Export CSV
            </Button>
          </div>

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
                  {labelsData.items.map((item) => (
                    <LabelRow key={item.id} item={item} />
                  ))}
                </tbody>
              </table>
            </div>

            {totalLabelPages > 1 && (
              <div className="flex items-center justify-center gap-3 px-4 py-3 border-t">
                <Button
                  variant="outline" size="icon"
                  onClick={() => setLabelsPage((p) => Math.max(0, p - 1))}
                  disabled={labelsPage === 0}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {labelsPage + 1} / {totalLabelPages}
                </span>
                <Button
                  variant="outline" size="icon"
                  onClick={() => setLabelsPage((p) => Math.min(totalLabelPages - 1, p + 1))}
                  disabled={labelsPage === totalLabelPages - 1}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function AttentionCardView({ card, onAction }: { card: AttentionCard; onAction: () => void }) {
  const actionLabel = card.action === "refine_taxonomy" ? "Refine taxonomy" : "Review queue";
  return (
    <Card className={cn("overflow-hidden", SEVERITY_BORDER[card.severity])}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full flex-shrink-0 mt-0.5", SEVERITY_DOT[card.severity])} />
            <p className="text-sm font-semibold capitalize">{card.title}</p>
          </div>
          <span className="text-xs tabular-nums text-muted-foreground font-medium">{card.count}</span>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed ml-4 mb-3">{card.detail}</p>
        <button
          onClick={onAction}
          className="ml-4 text-xs text-primary hover:underline font-medium"
        >
          {actionLabel} →
        </button>
      </CardContent>
    </Card>
  );
}

function CategoryTableRow({ row, total }: { row: CategoryRow; total: number }) {
  const isOther = row.category === "other";
  const pct = Math.round((row.count / (total || 1)) * 100);
  const sentTotal = (row.positive + row.negative + row.neutral) || 1;
  const negW = Math.round((row.negative / sentTotal) * 100);
  const posW = Math.round((row.positive / sentTotal) * 100);
  const neuW = Math.round((row.neutral / sentTotal) * 100);

  return (
    <tr className={cn("border-b last:border-0 hover:bg-secondary/30 transition-colors", isOther && "opacity-60")}>
      {/* Category */}
      <td className="px-4 py-2.5">
        <Badge variant="secondary" className="font-mono text-xs">{row.category}</Badge>
      </td>

      {/* Volume */}
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="tabular-nums text-foreground font-medium">{row.count}</span>
          <span className="text-muted-foreground text-2xs">({pct}%)</span>
        </div>
      </td>

      {/* Sentiment mini bar */}
      <td className="px-4 py-2.5">
        <div className="flex flex-col gap-0.5">
          <div className="flex h-1.5 w-20 rounded-full overflow-hidden gap-px">
            {negW > 0 && <div className="bg-red-400 h-full" style={{ width: `${negW}%` }} />}
            {posW > 0 && <div className="bg-green-500 h-full" style={{ width: `${posW}%` }} />}
            {neuW > 0 && <div className="bg-gray-300 h-full" style={{ width: `${neuW}%` }} />}
          </div>
          <div className="flex gap-2">
            <span className="text-2xs text-red-500">−{row.negative}</span>
            <span className="text-2xs text-green-600">+{row.positive}</span>
            <span className="text-2xs text-muted-foreground">~{row.neutral}</span>
          </div>
        </div>
      </td>

      {/* High urgency */}
      <td className="px-4 py-2.5">
        {row.high_urgency > 0 ? (
          <span className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded px-1.5 py-0.5 font-medium">
            {row.high_urgency} high
          </span>
        ) : (
          <span className="text-2xs text-muted-foreground">—</span>
        )}
      </td>

      {/* Top signal */}
      <td className="px-4 py-2.5 max-w-[180px]">
        {row.top_phrase ? (
          <span className="text-xs text-muted-foreground italic truncate block">"{row.top_phrase}"</span>
        ) : (
          <span className="text-2xs text-muted-foreground">—</span>
        )}
      </td>
    </tr>
  );
}

function LabelRow({ item }: { item: LabeledItem }) {
  return (
    <tr className="border-b last:border-0 hover:bg-secondary/30 transition-colors">
      <td className="px-4 py-2.5 max-w-[300px]">
        <p className="line-clamp-2 leading-relaxed text-foreground">{item.text}</p>
        {item.key_phrase && (
          <p className="text-2xs text-muted-foreground mt-0.5 truncate">"{item.key_phrase}"</p>
        )}
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
      <td className="px-4 py-2.5 tabular-nums text-muted-foreground">
        {Math.round(item.confidence * 100)}%
      </td>
      <td className="px-4 py-2.5">
        <span className={cn(
          "text-2xs font-medium rounded px-1.5 py-0.5",
          item.source === "human" ? "bg-green-50 text-green-700" : "bg-secondary text-muted-foreground"
        )}>
          {item.source === "human" ? "Human" : "AI"}
        </span>
      </td>
    </tr>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center pt-24">
      <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
