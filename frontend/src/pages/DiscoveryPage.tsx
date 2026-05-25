import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Trash2, Lock, Unlock, Sparkles, ArrowRight, Pin, PinOff, Download, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/Layout";
import { cn, toLabelKey } from "@/lib/utils";
import {
  startDiscovery, confirmDiscovery, getEnumConfig, getAvailableTaxonomies, importTaxonomy,
  useProjectTaxonomy as fetchProjectTaxonomy, type EnumCategory, type TaxonomySource,
} from "@/api/discovery";
import { getRun } from "@/api/runs";
import { getProject } from "@/api/projects";

interface CategoryCard extends EnumCategory { _id: string; keyLocked: boolean; pinned: boolean; }

let _seq = 0;
function uid() { return `c${++_seq}`; }
function toCard(cat: EnumCategory, pinned = false): CategoryCard {
  return { ...cat, _id: uid(), keyLocked: false, pinned };
}

export function DiscoveryPage() {
  const { runId } = useParams<{ runId: string }>();
  const rid = runId!;
  const navigate = useNavigate();

  const [cards, setCards] = useState<CategoryCard[]>([]);
  const [phase, setPhase] = useState<"idle" | "loading" | "editing" | "confirming">("idle");
  const [createdBy, setCreatedBy] = useState<string>("discovery");
  const [error, setError] = useState<string | null>(null);

  const { data: existingConfig } = useQuery({
    queryKey: ["enum-config", rid],
    queryFn: () => getEnumConfig(rid),
    enabled: !!rid,
  });

  const { data: availableTaxonomies = [] } = useQuery<TaxonomySource[]>({
    queryKey: ["available-taxonomies", rid],
    queryFn: () => getAvailableTaxonomies(rid),
    enabled: !!rid,
  });

  const { data: run } = useQuery({
    queryKey: ["run", rid],
    queryFn: () => getRun(rid),
    enabled: !!rid,
  });

  const { data: project } = useQuery({
    queryKey: ["project", run?.project_id],
    queryFn: () => getProject(run!.project_id!),
    enabled: !!run?.project_id,
  });

  const projectTaxonomyMutation = useMutation({
    mutationFn: () => fetchProjectTaxonomy(rid),
    onSuccess: (cats) => {
      setCards(cats.map((c) => toCard(c)));
      setCreatedBy("imported");
      setPhase("editing");
      setError(null);
    },
    onError: (e: Error) => { setError(e.message); },
  });

  useEffect(() => {
    if (existingConfig?.categories && phase === "idle") {
      const cats = Array.isArray(existingConfig.categories)
        ? (existingConfig.categories as EnumCategory[])
        : Object.values(existingConfig.categories as Record<string, EnumCategory>);
      setCards(cats.filter((c) => c.key !== "other").map((c) => toCard(c)));
      setPhase("editing");
    }
  }, [existingConfig, phase]);

  const discoverMutation = useMutation({
    mutationFn: (locked: EnumCategory[]) => startDiscovery(rid, locked),
    onSuccess: (suggested) => {
      setCards((prev) => {
        // Keep pinned cards, replace non-pinned with new suggestions
        const pinnedCards = prev.filter((c) => c.pinned);
        const pinnedKeys = new Set(pinnedCards.map((c) => c.key));
        const newCards = suggested
          .filter((s) => !pinnedKeys.has(s.key))
          .map((s) => toCard(s));
        return [...pinnedCards, ...newCards];
      });
      setPhase("editing");
      setError(null);
    },
    onError: (e: Error) => { setError(e.message); setPhase("editing"); },
  });

  const importMutation = useMutation({
    mutationFn: (sourceRunId: string) => importTaxonomy(rid, sourceRunId),
    onSuccess: (cats) => {
      setCards(cats.map((c) => toCard(c)));
      setCreatedBy("imported");
      setPhase("editing");
      setError(null);
    },
    onError: (e: Error) => { setError(e.message); },
  });

  const confirmMutation = useMutation({
    mutationFn: (cats: EnumCategory[]) => confirmDiscovery(rid, cats, createdBy),
    onSuccess: () => navigate(`/run/${rid}/extract`),
    onError: (e: Error) => { setError(e.message); setPhase("editing"); },
  });

  function updateCard(id: string, patch: Partial<CategoryCard>) {
    setCards((prev) => prev.map((c) => {
      if (c._id !== id) return c;
      const updated = { ...c, ...patch };
      if ("label" in patch && !c.keyLocked) updated.key = toLabelKey(patch.label ?? "");
      return updated;
    }));
  }

  function handleReDiscover() {
    const pinned = cards.filter((c) => c.pinned).map(({ key, label, description }) => ({ key, label, description }));
    setPhase("loading");
    setError(null);
    discoverMutation.mutate(pinned);
  }

  function handleConfirm() {
    const valid = cards.filter((c) => c.key && c.label);
    if (valid.length === 0) { setError("Add at least one category."); return; }
    const keys = valid.map((c) => c.key);
    const dupes = keys.filter((k, i) => keys.indexOf(k) !== i);
    if (dupes.length > 0) { setError(`Duplicate keys: ${[...new Set(dupes)].join(", ")}`); return; }
    setPhase("confirming");
    setError(null);
    confirmMutation.mutate(valid.map(({ key, label, description }) => ({ key, label, description })));
  }

  /* ── Idle ── */
  if (phase === "idle") {
    const hasProjectTaxonomy = !!project?.taxonomy_run_id;
    const anyPending = discoverMutation.isPending || importMutation.isPending || projectTaxonomyMutation.isPending;

    return (
      <div>
        <PageHeader
          title="Discover categories"
          subtitle="GrainSift samples your feedback and suggests a taxonomy."
          breadcrumb={[{ label: "Runs", href: "/" }]}
        />
        <div className="max-w-lg space-y-4">
          {/* Project taxonomy shortcut */}
          {hasProjectTaxonomy && (
            <Card className="border-green-200 bg-green-50/40">
              <CardContent className="p-6 flex flex-col items-center text-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-green-100 flex items-center justify-center">
                  <FolderOpen className="h-6 w-6 text-green-600" />
                </div>
                <div>
                  <p className="font-medium mb-1">Use project taxonomy</p>
                  <p className="text-sm text-muted-foreground max-w-xs">
                    Reuse the categories already established for this project — no LLM call needed.
                  </p>
                </div>
                <Button
                  variant="outline"
                  className="border-green-300 hover:bg-green-100"
                  onClick={() => projectTaxonomyMutation.mutate()}
                  disabled={anyPending}
                >
                  <FolderOpen className="mr-2 h-4 w-4" />
                  {projectTaxonomyMutation.isPending ? "Loading…" : "Load project taxonomy"}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Primary action */}
          <Card>
            <CardContent className="p-8 flex flex-col items-center text-center gap-5">
              <div className="h-12 w-12 rounded-xl bg-blue-50 flex items-center justify-center">
                <Sparkles className="h-6 w-6 text-blue-500" />
              </div>
              <div>
                <p className="font-medium mb-1">AI-powered taxonomy discovery</p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  One LLM call samples up to 250 rows and returns suggested categories.
                  You review and edit before anything is labeled.
                </p>
              </div>
              <Button
                onClick={() => { setPhase("loading"); discoverMutation.mutate([]); }}
                disabled={anyPending}
              >
                <Sparkles className="mr-2 h-4 w-4" />
                Suggest categories
              </Button>
              {error && <p className="text-destructive text-sm">{error}</p>}
            </CardContent>
          </Card>

          {/* Import from previous run */}
          {availableTaxonomies.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 px-1">
                Or import from a previous run
              </p>
              <div className="space-y-2">
                {availableTaxonomies.map((t) => (
                  <button
                    key={t.run_id}
                    onClick={() => importMutation.mutate(t.run_id)}
                    disabled={anyPending}
                    className="w-full flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left hover:border-primary/50 hover:bg-secondary/50 transition-colors disabled:opacity-50"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <Download className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{t.filename}</p>
                        <p className="text-xs text-muted-foreground">
                          {t.category_count} categories
                          {t.categories.slice(0, 3).map((c) => ` · ${c.label}`)}
                          {t.category_count > 3 && " …"}
                        </p>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ── Loading ── */
  if (phase === "loading") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 pt-24">
        <div className="h-7 w-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-muted-foreground">Analyzing your feedback…</p>
      </div>
    );
  }

  /* ── Editing ── */
  const pinnedCount = cards.filter((c) => c.pinned).length;

  return (
    <div>
      <PageHeader
        title="Edit categories"
        subtitle={`${cards.length} categor${cards.length !== 1 ? "ies" : "y"} · "other" is always added automatically`}
        breadcrumb={[{ label: "Runs", href: "/" }]}
        action={
          <div className="flex items-center gap-2">
            {pinnedCount > 0 && (
              <span className="text-xs text-muted-foreground">
                {pinnedCount} pinned
              </span>
            )}
            <Button
              variant="outline" size="sm"
              onClick={handleReDiscover}
              disabled={discoverMutation.isPending || phase === "confirming"}
            >
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              {pinnedCount > 0 ? `Re-suggest (keeping ${pinnedCount})` : "Re-suggest"}
            </Button>
          </div>
        }
      />

      {pinnedCount > 0 && (
        <p className="text-xs text-muted-foreground mb-3 -mt-3 max-w-2xl">
          Pinned categories will be preserved when you re-suggest.
        </p>
      )}

      <div className="max-w-2xl space-y-2.5">
        {cards.map((card) => (
          <CategoryCardRow
            key={card._id}
            card={card}
            onChange={(patch) => updateCard(card._id, patch)}
            onLockKey={() => setCards((prev) => prev.map((c) => c._id === card._id ? { ...c, keyLocked: !c.keyLocked } : c))}
            onTogglePin={() => setCards((prev) => prev.map((c) => c._id === card._id ? { ...c, pinned: !c.pinned } : c))}
            onDelete={() => setCards((prev) => prev.filter((c) => c._id !== card._id))}
          />
        ))}

        {/* Other hint */}
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed bg-secondary/50">
          <Badge variant="outline" className="font-mono text-xs shrink-0">other</Badge>
          <p className="text-xs text-muted-foreground">
            Feedback that doesn't match any category above is automatically labeled <em>other</em>.
          </p>
        </div>

        {/* Add button */}
        <button
          onClick={() => setCards((prev) => [...prev, { _id: uid(), key: "", label: "", description: "", keyLocked: false, pinned: false }])}
          className="w-full flex items-center justify-center gap-2 py-2.5 border-2 border-dashed border-border rounded-xl text-sm text-muted-foreground hover:border-primary/50 hover:bg-secondary/50 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add category
        </button>
      </div>

      {error && <p className="text-destructive text-sm mt-4">{error}</p>}

      <div className="flex justify-end gap-2 mt-6 max-w-2xl">
        <Button variant="outline" onClick={() => navigate(`/`)} disabled={phase === "confirming"}>
          Back
        </Button>
        <Button onClick={handleConfirm} disabled={phase === "confirming" || cards.length === 0}>
          {phase === "confirming" ? "Saving…" : "Confirm & start labeling"}
          <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function CategoryCardRow({ card, onChange, onLockKey, onTogglePin, onDelete }: {
  card: CategoryCard;
  onChange: (patch: Partial<CategoryCard>) => void;
  onLockKey: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className={cn(card.pinned && "border-blue-300 bg-blue-50/30")}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <Input
            placeholder="Category label"
            value={card.label}
            onChange={(e) => onChange({ label: e.target.value })}
            className="font-medium"
          />
          {/* Pin button */}
          <button
            onClick={onTogglePin}
            title={card.pinned ? "Unpin (will be replaced on re-suggest)" : "Pin (keep on re-suggest)"}
            className={cn(
              "p-1 shrink-0 transition-colors",
              card.pinned ? "text-blue-500 hover:text-blue-600" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {card.pinned ? <Pin className="h-4 w-4" /> : <PinOff className="h-4 w-4" />}
          </button>
          <button onClick={onDelete} className="text-muted-foreground hover:text-destructive transition-colors p-1 shrink-0">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs text-muted-foreground w-16 shrink-0">key</span>
          <div className="flex items-center gap-1.5 flex-1">
            <Input
              value={card.key}
              onChange={(e) => onChange({ key: e.target.value, keyLocked: true })}
              disabled={!card.keyLocked}
              placeholder="auto"
              className={cn("font-mono text-xs h-8", !card.keyLocked && "text-muted-foreground bg-muted")}
            />
            <button onClick={onLockKey} className="text-muted-foreground hover:text-foreground p-1 shrink-0"
              title={card.keyLocked ? "Auto-generate from label" : "Edit manually"}>
              {card.keyLocked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-16 shrink-0">desc</span>
          <Input
            placeholder="Description (optional)"
            value={card.description}
            onChange={(e) => onChange({ description: e.target.value })}
            className="text-xs h-8 text-muted-foreground"
          />
        </div>
      </CardContent>
    </Card>
  );
}
