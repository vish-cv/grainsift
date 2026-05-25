<div align="center">

<h1>🌾 GrainSift</h1>

**Turn a CSV of raw customer feedback into structured labels, a review queue, dashboards, and a grounded AI query engine — all running locally.**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Self-hosted](https://img.shields.io/badge/Deployment-Self--hosted-blueviolet)](#quick-start)
[![Ollama compatible](https://img.shields.io/badge/LLM-Anthropic_%7C_OpenAI_%7C_Gemini_%7C_Ollama-black)](#configuration)

</div>

---

## The problem

You have 10,000 support tickets, app store reviews, or survey responses. You need to know: *what are users actually complaining about, and what's urgent?*

Sending raw feedback to a SaaS tool leaks PII. Hardcoding category labels misses what your users actually say. Manual review doesn't scale. LLM prompts with no validation silently mislabel. And pasting a CSV into ChatGPT every quarter gives you a different taxonomy each time — so you can never compare periods or track trends.

GrainSift is a structured pipeline — not a prompt wrapper.

---

## How it works

```
┌──────────┐   ┌───────────┐   ┌────────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐
│  Upload  │──▶│  Ingest   │──▶│  Discover  │──▶│  Label   │──▶│  Review  │──▶│  Query  │──▶│ Summary │
│  CSV     │   │ PII · Dedup│   │  Taxonomy  │   │  w/ LLM  │   │  Queue   │   │   AI    │   │   AI    │
└──────────┘   └───────────┘   └────────────┘   └──────────┘   └──────────┘   └─────────┘   └─────────┘
                   Stage 1          Stage 2         Stage 3       Stage 4-5      Stage 6-7     Stage 8
```

Every stage is auditable. Every decision is stored. Nothing is silently discarded.

---

## What makes it different

| | GrainSift | SaaS tools | Raw LLM prompts |
|--|--|--|--|
| Data stays local | ✅ | ❌ | Depends |
| PII redacted before storage | ✅ | ❌ | ❌ |
| Categories from your data | ✅ | ❌ (fixed schema) | ❌ (you write them) |
| Taxonomy versioned across runs | ✅ | ❌ | ❌ |
| Confidence-based review queue | ✅ | ❌ | ❌ |
| Corrections tracked separately | ✅ | ❌ | ❌ |
| Cross-run trend tracking | ✅ | Rarely | ❌ |
| Works with local models | ✅ Ollama | ❌ | Sometimes |

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Install and run

```bash
# 1. Clone and install
git clone https://github.com/your-org/grainsift && cd grainsift
uv sync

# 2. Configure your LLM
cp .env.example .env
# Edit .env — set LLM_PROVIDER and add your API key (see Configuration below)

# 3. Start the backend
uv run grainsift start --reload

# 4. In a separate terminal, start the frontend
cd frontend && npm install && npm run dev
```

Open the URL shown in the frontend terminal output and upload a CSV.

> **Tip:** `grainsift start --reload` watches for code changes automatically. For production use, drop `--reload`.

---

## The engine

### Stage 1 — Ingest & clean

Raw text is cleaned and structured before any LLM sees it.

- **PII redaction** — detects and replaces email, phone, SSN, IP address, credit card, street address, and names with typed tokens (`[EMAIL]`, `[SSN]`) before writing to the database. The original text is never stored.
- **Deduplication** — SHA-256 content hash. No embedding model, no similarity threshold to tune.
- **Language detection** — flags non-English items for review rather than silently mislabeling them. Non-English items are translated automatically before labeling.
- **Chunking** — splits items that exceed the token limit and re-merges them before labeling.

### Stage 2 — Taxonomy discovery

The LLM proposes categories from a sample of your actual data. You approve before anything is labeled.

```
Sample 250 items  →  LLM discovers categories  →  You review & edit  →  Lock version
```

Rules enforced on every discovery run:
- Every category must appear in at least 2 items
- Categories must be mutually exclusive
- No generic "other" (added automatically as a catch-all)
- Categories are versioned — extraction is always tied to the version you confirmed

**Taxonomy inheritance** — once a project's first run confirms a taxonomy, every subsequent run in that project can reuse those exact categories with one click. No LLM call, no drift.

**Pin & re-suggest** — pin specific categories you want to keep and re-run discovery to fill the gaps around them.

### Stage 3 — AI labeling

Each item is classified in batches using [Instructor](https://github.com/instructor-ai/instructor), which wraps the LLM with a dynamically-built Pydantic schema. The `category` field is constrained to an enum of exactly your confirmed keys — the model cannot produce an out-of-vocabulary label.

Each label includes: `category · sentiment · urgency · key_phrase · confidence`

### Stage 4 — Validation routing

Every label is evaluated before it's confirmed. Items that fail routing rules go to the review queue instead of being auto-confirmed.

| Flag | Trigger | Always queued? |
|------|---------|---------------|
| `language_flag` | non-English detected | Yes |
| `schema_retry` | LLM failed schema validation | Yes |
| `high_urgency_low_confidence` | high urgency + confidence below threshold | Yes |
| `low_confidence` | confidence below threshold | If paired with another flag |
| `category_other` | item classified as "other" | Yes |
| `random_sample` | 5% random quality sample | Yes |

### Stage 5 — Human review queue

Flagged items surface in a priority queue sorted by urgency then confidence.

- **Confirm** — accept the LLM label as-is
- **Edit** — correct category and/or sentiment; creates a `Correction` record (original prediction preserved)
- **Skip** — return to the bottom of the queue
- **Bulk actions** — confirm all on page, or move a selection to a different category

Taxonomy changed after labeling? Items whose category no longer exists are automatically re-flagged and returned to the queue.

### Stage 6 — Dashboards & export

Pure pandas. No LLM calls.

- Volume by category · sentiment breakdown · urgency distribution
- Key phrase clusters (exact-match counts per category, top 5 per category)
- Daily time series with per-category breakdown
- Per-category model accuracy from human corrections
- Confusion matrix (original LLM label → human correction)
- Confidence bucket accuracy (how accurate is the model when it says 85%+ confidence?)
- One-click CSV export

### Stage 7 — Query engine

Ask plain-language questions about your labeled feedback. Answers are grounded in the actual data.

```
Q: What are users complaining about most?
A: Order delivery issues (10 items, all negative) and product quality (9 items) are the 
   top complaints. 73% of all feedback is negative. 24 of 49 items are high urgency.
   Confidence: high | Sources: 4 verbatim quotes

Q: Which of those are high urgency?        ← follow-up, references prior answer
A: All 10 order delivery items are high urgency. 3 of 9 product quality items are high...
```

- No vector database. Retrieval uses keyword matching + urgency sampling.
- Every query receives the full aggregate stats so the model can answer "how many" questions accurately.
- **Multi-turn** — last 5 exchanges from the same session are included in each prompt.
- **Persistent** — all conversations saved to SQLite, grouped by session, survive page refreshes.

### Stage 8 — AI summary

Generate a 3-paragraph executive summary for any completed run. One click, one LLM call. References specific numbers from the labeled data — volume by category, sentiment split, urgency distribution, and human review accuracy. Can be regenerated at any time.

---

## Projects

Group related runs under a project to track the same feedback source over time.

- **Shared taxonomy** — the first confirmed taxonomy in a project becomes the default for all future runs. New runs skip discovery and go straight to labeling.
- **Per-project prompt overrides** — customize the discovery, extraction, and query prompts per project without affecting the global defaults.
- **Cross-run visibility** — see all runs for a project in one place with status, row counts, and flagged item counts.

---

## Prompt customization

All LLM prompts are editable without touching code. Three-level fallback:

```
Project override  →  Global default (Settings page)  →  Hardcoded constant
```

Editable prompts: `discovery_system`, `discovery_user`, `extraction_system`, `query_system`, `summary_system`, `summary_user`

---

## Configuration

```bash
# .env

# ─── LLM Provider ────────────────────────────────────────────────────────────
LLM_PROVIDER=anthropic          # anthropic | openai | gemini | ollama

# ─── API Keys (only set the one you use) ─────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...

# ─── Model Selection ─────────────────────────────────────────────────────────
ANTHROPIC_MODEL=claude-sonnet-4-6        # or claude-haiku-4-5-20251001
OPENAI_MODEL=gpt-4o                      # or gpt-4o-mini
GEMINI_MODEL=gemini-2.0-flash            # or gemini-1.5-pro
OLLAMA_MODEL=llama3.2                    # or mistral | phi3
OLLAMA_BASE_URL=http://localhost:11434

# ─── Database ────────────────────────────────────────────────────────────────
# Defaults to ~/.grainsift/grainsift.db (SQLite). Override for PostgreSQL:
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/grainsift
DATABASE_URL=

# ─── Processing ──────────────────────────────────────────────────────────────
BATCH_SIZE=5                  # items per LLM call (1–10)
CONFIDENCE_THRESHOLD=0.65     # below this → human review queue
MAX_FEEDBACK_WORDS=400        # items longer than this get chunked
```

---

## Stack

| Layer | |
|-------|---|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy 2.x async |
| Database | SQLite with WAL mode · zero config · single file |
| LLM integration | Instructor · Anthropic · OpenAI · Gemini · Ollama |
| Frontend | React 18 · TypeScript · Vite · TanStack Query · Tailwind CSS v3 |
| PII detection | Regex-based · no external API · no data transmitted |
| Language detection | `langdetect` · runs locally |

---

## Project structure

```
grainsift/
├── engine/
│   ├── ingest.py            # Stage 1: PII, dedup, lang detect, chunking
│   ├── discovery.py         # Stage 2: taxonomy discovery + versioning
│   ├── extraction.py        # Stage 3: batch LLM labeling with Instructor
│   ├── validation.py        # Stage 4: routing rules (pure functions, no I/O)
│   ├── aggregation.py       # Stage 5+6: review queue + pandas stats
│   ├── calibration.py       # Stage 6: accuracy + confusion matrix
│   ├── query.py             # Stage 7: grounded Q&A with session persistence
│   ├── summarization.py     # Stage 8: AI executive summary
│   └── prompt_store.py      # 3-level prompt fallback (project → global → hardcoded)
├── api/routes/              # One FastAPI router per stage
│   ├── projects.py          # Project CRUD + run listing
│   ├── prompts.py           # Global + per-project prompt overrides
│   └── ...
├── llm/
│   ├── prompts.py           # All hardcoded prompt constants
│   └── providers/           # Anthropic / OpenAI / Gemini / Ollama adapters
└── models/
    ├── database.py          # SQLAlchemy ORM models
    ├── enums.py             # StrEnum for all categorical values
    └── schemas.py           # Pydantic v2 request/response schemas
```

---

## License

MIT — see [LICENSE](LICENSE)
