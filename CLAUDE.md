# GrainSift — Claude Context

GrainSift is a structured feedback analysis pipeline. Upload a CSV of customer feedback, run it through 8 stages (ingest → discover taxonomy → label → validate → review → dashboard → query → summarize), get structured labels, dashboards, and a grounded AI query engine — all running locally.

---

## How to run

```bash
# Backend (from project root)
uv run grainsift start --reload       # runs on port 8000

# Frontend (separate terminal)
cd frontend && npm run dev             # runs on port 5173
```

Health check: `curl http://localhost:8000/health`

If port 8000 is taken by another process: `lsof -i :8000` to find it, `kill <PID>` to clear it.

---

## Stack

| Layer | |
|-------|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x async, Pydantic v2 |
| Database | SQLite WAL mode (default) · `~/.grainsift/grainsift.db` |
| LLM | Instructor-based · Anthropic / OpenAI / Gemini / Ollama |
| Frontend | React 18, TypeScript, Vite, TanStack Query, Tailwind CSS v3 |

---

## Project structure

```
grainsift/
├── engine/
│   ├── ingest.py          # Stage 1: PII, dedup, lang detect, chunking
│   ├── discovery.py       # Stage 2: taxonomy discovery + versioning
│   ├── extraction.py      # Stage 3: batch LLM labeling via Instructor
│   ├── validation.py      # Stage 4: routing rules (pure functions, no I/O)
│   ├── aggregation.py     # Stage 5+6: review queue, pandas stats, attention signals
│   ├── calibration.py     # Stage 6: accuracy + confusion matrix
│   ├── query.py           # Stage 7: grounded Q&A, session persistence
│   ├── summarization.py   # Stage 8: AI executive summary
│   └── prompt_store.py    # 3-level prompt fallback
├── api/routes/            # One FastAPI router per domain
├── llm/providers/         # Anthropic / OpenAI / Gemini / Ollama adapters
└── models/
    ├── database.py        # SQLAlchemy ORM
    ├── enums.py           # StrEnum for all categorical values
    └── schemas.py         # Pydantic v2 request/response schemas

frontend/src/
├── api/                   # One TS file per domain (runs.ts, dashboard.ts, etc.)
├── pages/                 # One component per page
└── components/            # Shared UI (Layout, shadcn/ui components)
```

---

## Key conventions

**Backend**
- All DB access is `async` via `AsyncSession` — never use sync SQLAlchemy
- Migrations are inline in `api/main.py` at startup: check `PRAGMA table_info`, then `ALTER TABLE ADD COLUMN`
- LLM calls always go through `BaseLLMProvider.complete(messages, ResponseModel)` — Instructor-based, always requires a Pydantic `response_model`. For free-form text output, wrap in a single-field model: `class Result(BaseModel): text: str`
- Prompt fallback: project override → global `AppConfig` → hardcoded constant in `llm/prompts.py`
- Route files use `DbSession` and `LLMClient` from `api/deps.py`

**Frontend**
- TanStack Query: `queryKey: ["resource", id]` — invalidate with `useQueryClient().invalidateQueries`
- API calls go in `frontend/src/api/` — never fetch directly from page components
- No comments unless the WHY is non-obvious

**General**
- No backwards-compat shims, no unused variables, no half-finished implementations
- Don't add error handling for things that can't happen

---

## Database schema

```
Run
 └── RawFeedback (run_id FK)
      └── Label (feedback_id FK)
           └── Correction (label_id FK)  ← created when human edits a label

Project
 ├── taxonomy_run_id  ← set after first confirmed run, reused by subsequent runs
 └── prompt overrides (per-project)
```

Run has: `status`, `summary` (ingest JSON), `ai_summary` (generated text), `actual_cost`, `model_used`

---

## What's been built (current state)

All 8 pipeline stages are complete and working:

- **Stage 1–3**: Ingest, taxonomy discovery with versioning, batch extraction
- **Stage 4–5**: Validation routing + human review queue (confirm / edit / skip / bulk)
- **Stage 6**: Dashboard redesigned — briefing line, attention cards (priority-scored), unified category breakdown table, verbatim quotes. Endpoint: `GET /runs/{id}/dashboard/attention`
- **Stage 7**: Query engine with multi-turn sessions, keyword + urgency retrieval, no vector DB
- **Stage 8**: AI executive summary — `POST /runs/{id}/summary` generates, `GET /runs/{id}/summary` retrieves
- **Projects**: Group runs, shared taxonomy inheritance, per-project prompt overrides
- **Settings**: Global prompt overrides via `AppConfig`
- **Taxonomy shortcuts**: DiscoveryPage has "Use project taxonomy" card (skips LLM discovery)

**Frontend routes**
```
/                          → ProjectsPage
/projects/:projectId       → ProjectPage
/runs                      → RunsPage
/upload                    → UploadPage
/run/:runId                → RunPage (tabs: Overview, Insights, Data, Ask AI, Quality)
/run/:runId/discovery      → DiscoveryPage
/run/:runId/extract        → ExtractPage
/run/:runId/review         → ReviewPage
/run/:runId/dashboard      → DashboardPage (standalone, linked from PipelinePage)
/settings                  → SettingsPage
```

**RunPage tabs**
- **Overview** — pipeline stage summary, ingest stats, AI summary section
- **Insights** — attention signals: briefing line + priority cards + category table + verbatim quotes
- **Data** — filterable/searchable labeled items table
- **Ask AI** — multi-turn query engine
- **Quality** — accuracy + confusion matrix from human corrections

---

## GitHub

Repo: `https://github.com/vish-cv/grainsift`
Git user: `vish-cv / vishwanthcv95@proton.me`
Status: committed locally, remote not yet pushed (user will push manually)

---

## Things to know

- The `SENTIMENT_COLORS`, `URGENCY_BADGE`, `SENTIMENT_BADGE` constants are defined in both `RunPage.tsx` and `DashboardPage.tsx` — not yet extracted to a shared file
- `InsightsTab` in `RunPage.tsx` uses `getAttentionSignals` (the new endpoint) — not `getDashboardStats`
- `DashboardPage.tsx` (standalone) also renders attention signals + labeled items table for the pipeline flow
- The `.claude/commands/grainsift.md` skill file exists but requires a fresh Claude Code session to activate
