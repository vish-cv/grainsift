import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, SkipForward, ChevronLeft, ChevronRight, Languages } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import { getReviewQueue, submitReviewDecision, bulkReviewDecision, type ReviewItem } from "@/api/dashboard";
import { getEnumCategories } from "@/api/discovery";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

const URGENCY_STYLE: Record<string, string> = {
  critical: "text-red-700 bg-red-50 border-red-200",
  high:     "text-orange-700 bg-orange-50 border-orange-200",
  medium:   "text-yellow-700 bg-yellow-50 border-yellow-200",
  low:      "text-muted-foreground bg-secondary border-border",
};

const FLAG_REASON: Record<string, string> = {
  low_confidence: "Low confidence",
  high_urgency: "High urgency — verify",
  non_english: "Non-English text",
  schema_retry: "LLM needed retries",
  random_sample: "Quality check sample",
  short_text: "Very short text",
  mixed_language: "Mixed languages",
  category_orphaned: "Category removed from taxonomy",
};

export function ReviewPage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editCategory, setEditCategory] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkCategory, setBulkCategory] = useState("");

  const { data: queue, isLoading } = useQuery({
    queryKey: ["review", rid, page],
    queryFn: () => getReviewQueue(rid, page, PAGE_SIZE),
    enabled: !!rid,
  });

  const { data: categories = [] } = useQuery({
    queryKey: ["categories", rid],
    queryFn: () => getEnumCategories(rid),
    enabled: !!rid,
    select: (cats) => cats.map((c) => c.key),
  });

  const decideMutation = useMutation({
    mutationFn: ({ labelId, action, cat }: { labelId: string; action: "confirm" | "edit" | "skip"; cat?: string }) =>
      submitReviewDecision(rid, labelId, action, cat),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["review", rid] }); setEditingId(null); },
  });

  const bulkMutation = useMutation({
    mutationFn: ({ action, cat }: { action: "confirm" | "edit"; cat?: string }) =>
      bulkReviewDecision(rid, Array.from(selectedIds), action, cat),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review", rid] });
      setSelectedIds(new Set());
      setBulkCategory("");
    },
  });

  const toggleSelect = useCallback((labelId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(labelId)) next.delete(labelId);
      else next.add(labelId);
      return next;
    });
  }, []);

  const allPageSelected = (queue?.items ?? []).length > 0 &&
    (queue?.items ?? []).every((item) => selectedIds.has(item.label_id));

  const toggleSelectAll = useCallback(() => {
    if (!queue) return;
    if (allPageSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        queue.items.forEach((item) => next.delete(item.label_id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        queue.items.forEach((item) => next.add(item.label_id));
        return next;
      });
    }
  }, [queue, allPageSelected]);

  const totalPages = queue ? Math.ceil(queue.total / PAGE_SIZE) : 1;

  // Keyboard shortcuts — Y confirm, E edit, S skip the first item in list
  const handleConfirm = useCallback((item: ReviewItem) => {
    decideMutation.mutate({ labelId: item.label_id, action: "confirm" });
  }, [decideMutation]);

  const handleEdit = useCallback((item: ReviewItem) => {
    setEditingId(item.id);
    setEditCategory(item.category ?? "");
  }, []);

  const handleSkip = useCallback((item: ReviewItem) => {
    decideMutation.mutate({ labelId: item.label_id, action: "skip" });
  }, [decideMutation]);

  useEffect(() => {
    const firstItem = queue?.items[0];
    if (!firstItem) return;

    const onKey = (e: KeyboardEvent) => {
      // Don't fire shortcuts when user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement) return;
      if (editingId) return;
      if (decideMutation.isPending) return;

      if (e.key === "y" || e.key === "Y") handleConfirm(firstItem);
      if (e.key === "e" || e.key === "E") handleEdit(firstItem);
      if (e.key === "s" || e.key === "S") handleSkip(firstItem);
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, editingId, decideMutation.isPending, handleConfirm, handleEdit, handleSkip]);

  if (isLoading) return <Spinner />;
  if (!queue) return null;

  return (
    <div>
      <PageHeader
        title="Review queue"
        subtitle={`${queue.total} items flagged for human review`}
        breadcrumb={[{ label: "Runs", href: "/" }]}
        action={
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground hidden sm:block">
              <kbd className="px-1.5 py-0.5 rounded border border-border bg-secondary font-mono text-xs">Y</kbd> confirm ·{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-border bg-secondary font-mono text-xs">E</kbd> edit ·{" "}
              <kbd className="px-1.5 py-0.5 rounded border border-border bg-secondary font-mono text-xs">S</kbd> skip
            </span>
            <Button variant="outline" size="sm" onClick={() => navigate(`/run/${rid}`)}>
              Back to run
            </Button>
          </div>
        }
      />

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-primary/5 border border-primary/20 max-w-3xl">
          <span className="text-sm font-medium text-primary mr-1">{selectedIds.size} selected</span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            disabled={bulkMutation.isPending}
            onClick={() => bulkMutation.mutate({ action: "confirm" })}
          >
            <Check className="h-3 w-3 mr-1" /> Confirm all
          </Button>
          <div className="flex items-center gap-1 ml-auto">
            <select
              value={bulkCategory}
              onChange={(e) => setBulkCategory(e.target.value)}
              className="flex h-7 rounded-md border border-input bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Move to category…</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={!bulkCategory || bulkMutation.isPending}
              onClick={() => bulkMutation.mutate({ action: "edit", cat: bulkCategory })}
            >
              Apply
            </Button>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs text-muted-foreground"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear
          </Button>
        </div>
      )}

      {queue.items.length === 0 && (
        <div className="rounded-xl border-2 border-dashed border-border flex flex-col items-center justify-center py-20 text-center">
          <p className="text-sm font-medium mb-1">All caught up</p>
          <p className="text-sm text-muted-foreground">No more items in the review queue.</p>
        </div>
      )}

      {/* Select-all row */}
      {queue.items.length > 0 && (
        <div className="flex items-center gap-2 mb-2 max-w-3xl px-1">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-border accent-primary"
            checked={allPageSelected}
            onChange={toggleSelectAll}
          />
          <span className="text-xs text-muted-foreground">Select all on page</span>
        </div>
      )}

      <div className="space-y-2 max-w-3xl">
        {queue.items.map((item, idx) => (
          <ReviewCard
            key={item.id}
            item={item}
            categories={categories}
            isFirst={idx === 0}
            isEditing={editingId === item.id}
            editCategory={editCategory}
            onEditCategory={setEditCategory}
            onConfirm={() => handleConfirm(item)}
            onEdit={() => handleEdit(item)}
            onEditSubmit={() => decideMutation.mutate({ labelId: item.label_id, action: "edit", cat: editCategory })}
            onSkip={() => handleSkip(item)}
            onCancelEdit={() => setEditingId(null)}
            busy={decideMutation.isPending}
            selected={selectedIds.has(item.label_id)}
            onToggleSelect={() => toggleSelect(item.label_id)}
          />
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center gap-3 mt-5 max-w-3xl justify-center">
          <Button variant="outline" size="icon" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button variant="outline" size="icon" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

function ReviewCard({
  item, categories, isFirst, isEditing, editCategory, onEditCategory,
  onConfirm, onEdit, onEditSubmit, onSkip, onCancelEdit, busy, selected, onToggleSelect,
}: {
  item: ReviewItem; categories: string[]; isFirst: boolean;
  isEditing: boolean; editCategory: string;
  onEditCategory: (v: string) => void; onConfirm: () => void; onEdit: () => void;
  onEditSubmit: () => void; onSkip: () => void; onCancelEdit: () => void; busy: boolean;
  selected: boolean; onToggleSelect: () => void;
}) {
  const urgencyStyle = URGENCY_STYLE[item.urgency ?? "low"] ?? URGENCY_STYLE.low;
  const hasTranslation = !!item.translated_text;
  const translatedText = item.translated_text;

  return (
    <Card className={cn(isFirst && "ring-1 ring-primary/20", selected && "ring-1 ring-primary/40 bg-primary/5")}>
      <CardContent className="p-4">

        {/* Checkbox + flag reasons row */}
        <div className="flex items-start gap-2 mb-2">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 mt-0.5 shrink-0 rounded border-border accent-primary"
            checked={selected}
            onChange={onToggleSelect}
          />
          <div className="flex flex-wrap gap-1">
            {item.review_flags && item.review_flags.map((f) => (
              <span key={f} className="inline-flex items-center text-2xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
                {FLAG_REASON[f] ?? f.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>

        {/* Feedback text */}
        <p className="text-sm leading-relaxed mb-2">{item.text}</p>

        {/* Translated text */}
        {hasTranslation && (
          <div className="flex items-start gap-1.5 mb-2 rounded-md bg-blue-50 border border-blue-100 px-2.5 py-1.5">
            <Languages className="h-3.5 w-3.5 text-blue-500 mt-0.5 shrink-0" />
            <p className="text-xs text-blue-800 leading-relaxed">{translatedText}</p>
          </div>
        )}

        {/* Labels row */}
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          {item.category && (
            <Badge variant="secondary" className="font-mono text-xs">{item.category}</Badge>
          )}
          {item.sentiment && (
            <Badge variant="outline" className="text-xs">{item.sentiment}</Badge>
          )}
          {item.urgency && (
            <Badge variant="outline" className={cn("text-xs", urgencyStyle)}>
              {item.urgency}
            </Badge>
          )}
          {item.confidence != null && (
            <span className="ml-auto text-xs text-muted-foreground tabular-nums">
              {Math.round(item.confidence * 100)}% conf
            </span>
          )}
        </div>

        {isEditing ? (
          <div className="flex items-center gap-2">
            <select
              value={editCategory}
              onChange={(e) => onEditCategory(e.target.value)}
              className="flex h-8 flex-1 rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Button size="sm" onClick={onEditSubmit} disabled={busy}>Save</Button>
            <Button size="sm" variant="ghost" onClick={onCancelEdit}>Cancel</Button>
          </div>
        ) : (
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={onConfirm} disabled={busy} className="h-7 text-xs">
              <Check className="h-3 w-3 mr-1" /> Confirm
              {isFirst && <kbd className="ml-1.5 text-2xs opacity-50 font-mono">Y</kbd>}
            </Button>
            <Button size="sm" variant="outline" onClick={onEdit} disabled={busy} className="h-7 text-xs">
              <Pencil className="h-3 w-3 mr-1" /> Edit
              {isFirst && <kbd className="ml-1.5 text-2xs opacity-50 font-mono">E</kbd>}
            </Button>
            <Button size="sm" variant="ghost" onClick={onSkip} disabled={busy} className="h-7 text-xs text-muted-foreground">
              <SkipForward className="h-3 w-3 mr-1" /> Skip
              {isFirst && <kbd className="ml-1.5 text-2xs opacity-50 font-mono">S</kbd>}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center pt-24">
      <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
