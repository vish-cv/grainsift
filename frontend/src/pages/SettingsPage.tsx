import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, CheckCircle2, XCircle, Loader2, Zap, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/Layout";
import {
  getSettings,
  updateSettings,
  getModelList,
  testConnection,
  PROVIDER_LABELS,
  type TestResult,
} from "@/api/settings";
import {
  getGlobalPrompts,
  updateGlobalPrompt,
  resetGlobalPrompt,
  type PromptItem,
} from "@/api/prompts";
import { cn } from "@/lib/utils";

const PROVIDERS = ["anthropic", "openai", "gemini", "ollama"] as const;

const PROVIDER_META: Record<string, { color: string; description: string }> = {
  anthropic: { color: "bg-orange-500", description: "Claude models" },
  openai: { color: "bg-emerald-500", description: "GPT-4o, o1" },
  gemini: { color: "bg-blue-500", description: "Gemini Flash, Pro" },
  ollama: { color: "bg-purple-500", description: "Fully local" },
};

export function SettingsPage() {
  const qc = useQueryClient();

  const { data: saved, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const { data: modelList = {} } = useQuery({
    queryKey: ["settings-models"],
    queryFn: getModelList,
  });

  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434/v1");
  const [batchSize, setBatchSize] = useState(5);
  const [confidence, setConfidence] = useState(0.7);
  const [showKey, setShowKey] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  useEffect(() => {
    if (!saved) return;
    setProvider(saved.provider || "anthropic");
    setModel(saved.model || "");
    setOllamaUrl(saved.ollama_base_url || "http://localhost:11434/v1");
    setBatchSize(saved.batch_size);
    setConfidence(saved.confidence_threshold);
  }, [saved]);

  const models = modelList[provider] ?? [];

  function handleProviderChange(p: string) {
    setProvider(p);
    const opts = modelList[p] ?? [];
    setModel(opts[0] ?? "");
    setTestResult(null);
    setApiKey("");
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      updateSettings({
        provider,
        model,
        ...(apiKey ? { api_key: apiKey } : {}),
        ollama_base_url: ollamaUrl,
        batch_size: batchSize,
        confidence_threshold: confidence,
      }),
    onSuccess: (updated) => {
      qc.setQueryData(["settings"], updated);
      setApiKey("");
      setTestResult(null);
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      await saveMutation.mutateAsync();
      return testConnection();
    },
    onSuccess: (result) => setTestResult(result),
    onError: (e: Error) => setTestResult({ ok: false, message: e.message }),
  });

  if (isLoading) return <Spinner />;

  const isBusy = saveMutation.isPending || testMutation.isPending;

  return (
    <div className="max-w-2xl">
      <PageHeader
        title="Settings"
        subtitle="Configure the AI model used to analyze feedback."
      />

      {/* Status pill */}
      {saved && (
        <div className="mb-6">
          {saved.is_configured ? (
            <div className="inline-flex items-center gap-2 rounded-full bg-green-50 border border-green-200 px-3 py-1.5 text-xs font-medium text-green-700">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Connected · {PROVIDER_LABELS[saved.provider]} · {saved.model}
            </div>
          ) : (
            <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs font-medium text-amber-700">
              <XCircle className="h-3.5 w-3.5" />
              Not configured — add an API key to get started
            </div>
          )}
        </div>
      )}

      {/* LLM config card */}
      <Card className="mb-4">
        <CardContent className="p-6 space-y-6">

          {/* Provider */}
          <div>
            <label className="block text-sm font-medium mb-3">Provider</label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PROVIDERS.map((p) => {
                const meta = PROVIDER_META[p];
                const active = provider === p;
                return (
                  <button
                    key={p}
                    onClick={() => handleProviderChange(p)}
                    className={cn(
                      "relative rounded-lg border-2 p-3 text-left transition-all",
                      active
                        ? "border-primary bg-accent"
                        : "border-border bg-card hover:border-border hover:bg-secondary"
                    )}
                  >
                    <div className={cn("h-6 w-6 rounded-md mb-2 flex items-center justify-center", meta.color)}>
                      <Zap className="h-3.5 w-3.5 text-white" />
                    </div>
                    <div className="text-xs font-semibold">{PROVIDER_LABELS[p]}</div>
                    <div className="text-2xs text-muted-foreground mt-0.5">{meta.description}</div>
                    {active && (
                      <div className="absolute top-2 right-2">
                        <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Ollama URL */}
          {provider === "ollama" && (
            <div>
              <label className="block text-sm font-medium mb-1.5">Ollama server URL</label>
              <Input
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
                placeholder="http://localhost:11434/v1"
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                Start with <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-2xs">ollama serve</code>
              </p>
            </div>
          )}

          {/* API key */}
          {provider !== "ollama" && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-sm font-medium">API key</label>
                {saved?.api_key_set && (
                  <span className="text-xs text-muted-foreground">
                    Saved key: <code className="bg-muted px-1.5 py-0.5 rounded font-mono">{saved.api_key_preview}</code>
                  </span>
                )}
              </div>
              <div className="relative">
                <Input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={saved?.api_key_set ? "Paste new key to replace…" : "Paste your API key"}
                  className="pr-10 font-mono"
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                Stored locally in your database. Only sent to {PROVIDER_LABELS[provider]}.
              </p>
            </div>
          )}

          {/* Model */}
          <div>
            <label className="block text-sm font-medium mb-1.5">Model</label>
            {provider === "ollama" ? (
              <>
                <Input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. llama3.2, mistral, phi3"
                />
                <p className="text-xs text-muted-foreground mt-1.5">
                  Run <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-2xs">ollama pull &lt;model&gt;</code> first.
                </p>
              </>
            ) : (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            )}
          </div>

          {/* Test result */}
          {testResult && (
            <div className={cn(
              "flex items-start gap-2.5 rounded-lg px-4 py-3 text-sm border",
              testResult.ok
                ? "bg-green-50 text-green-800 border-green-200"
                : "bg-red-50 text-red-800 border-red-200"
            )}>
              {testResult.ok
                ? <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-green-600" />
                : <XCircle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />}
              <span>{testResult.message}</span>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1 border-t">
            <Button onClick={() => saveMutation.mutate()} disabled={isBusy} className="mt-4">
              {saveMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Save
            </Button>
            <Button
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={isBusy}
              className="mt-4"
            >
              {testMutation.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Save & test connection
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Advanced */}
      <Card className="mb-4">
        <CardContent className="p-6">
          <h3 className="text-sm font-semibold mb-4">Advanced</h3>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium mb-1.5">Batch size</label>
              <Input
                type="number"
                min={1}
                max={20}
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground mt-1.5">Rows per LLM call. Default: 5</p>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">Confidence threshold</label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={confidence}
                onChange={(e) => setConfidence(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground mt-1.5">Below this → review queue. Default: 0.7</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => saveMutation.mutate()} disabled={isBusy} className="mt-5">
            Save advanced
          </Button>
        </CardContent>
      </Card>

      {/* Global prompts */}
      <PromptsSection />
    </div>
  );
}

function PromptsSection() {
  const qc = useQueryClient();

  const { data: prompts, isLoading } = useQuery({
    queryKey: ["global-prompts"],
    queryFn: getGlobalPrompts,
  });

  const updateMutation = useMutation({
    mutationFn: ({ key, content }: { key: string; content: string }) =>
      updateGlobalPrompt(key, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["global-prompts"] }),
  });

  const resetMutation = useMutation({
    mutationFn: (key: string) => resetGlobalPrompt(key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["global-prompts"] }),
  });

  if (isLoading) return null;

  const items = Object.values(prompts ?? {});

  return (
    <div>
      <div className="mb-3">
        <h2 className="text-sm font-semibold">Prompts</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Global defaults used for all projects. Individual projects can override these.
        </p>
      </div>
      <div className="space-y-3">
        {items.map((p) => (
          <PromptCard
            key={p.key}
            prompt={p}
            onSave={(content) => updateMutation.mutate({ key: p.key, content })}
            onReset={() => resetMutation.mutate(p.key)}
            isSaving={updateMutation.isPending && updateMutation.variables?.key === p.key}
            isResetting={resetMutation.isPending && resetMutation.variables === p.key}
          />
        ))}
      </div>
    </div>
  );
}

function PromptCard({
  prompt,
  onSave,
  onReset,
  isSaving,
  isResetting,
  sourceLabel,
}: {
  prompt: PromptItem;
  onSave: (content: string) => void;
  onReset: () => void;
  isSaving: boolean;
  isResetting: boolean;
  sourceLabel?: string;
}) {
  const [draft, setDraft] = useState(prompt.content);
  const isDirty = draft !== prompt.content;

  // Reset draft when external content changes (after save/reset)
  useEffect(() => {
    setDraft(prompt.content);
  }, [prompt.content]);

  const sourceBadge: Record<string, { label: string; cls: string }> = {
    default: { label: "Default", cls: "bg-secondary text-muted-foreground" },
    global:  { label: "Customized", cls: "bg-blue-50 text-blue-700 border border-blue-200" },
    project: { label: "Project override", cls: "bg-purple-50 text-purple-700 border border-purple-200" },
  };
  const badge = sourceBadge[sourceLabel ?? prompt.source] ?? sourceBadge.default;

  return (
    <Card>
      <CardContent className="p-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium">{prompt.label}</p>
              <span className={cn("text-2xs px-1.5 py-0.5 rounded-full font-medium", badge.cls)}>
                {badge.label}
              </span>
              {prompt.read_only && (
                <span className="text-2xs px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                  Read-only
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{prompt.description}</p>
          </div>
        </div>

        {prompt.required_vars.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <span className="text-xs text-muted-foreground mr-1">Required vars:</span>
            {prompt.required_vars.map((v) => (
              <code key={v} className="text-2xs bg-muted px-1.5 py-0.5 rounded font-mono">
                {v}
              </code>
            ))}
          </div>
        )}

        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={prompt.read_only}
          rows={draft.split("\n").length + 2}
          className={cn(
            "w-full rounded-md border border-input bg-card px-3 py-2 text-xs font-mono resize-y focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            prompt.read_only && "opacity-60 cursor-not-allowed bg-secondary"
          )}
        />

        {!prompt.read_only && (
          <div className="flex items-center gap-2 justify-end">
            {prompt.source !== "default" && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-muted-foreground"
                disabled={isResetting}
                onClick={onReset}
              >
                <RotateCcw className="h-3 w-3 mr-1" />
                {isResetting ? "Resetting…" : "Reset to default"}
              </Button>
            )}
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={!isDirty || isSaving}
              onClick={() => onSave(draft)}
            >
              {isSaving ? "Saving…" : "Save"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Export PromptCard for reuse in ProjectPage
export { PromptCard };

function Spinner() {
  return (
    <div className="flex justify-center pt-24">
      <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
