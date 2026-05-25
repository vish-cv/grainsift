"""
All LLM prompts in one place.
Each prompt is a typed dataclass with system + user template fields.
Templates use str.format_map() so missing keys raise KeyError immediately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    system: str
    user_template: str

    def user(self, **kwargs: object) -> str:
        return self.user_template.format_map(kwargs)


# ─── Stage 3: Discovery ───────────────────────────────────────────────────────

DISCOVERY = Prompt(
    system=(
        "You are analyzing customer feedback for a product team. "
        "Your job is to identify recurring topics and issues from a sample of feedback. "
        "Return only valid JSON matching the exact schema. No explanation, no markdown, no extra text."
    ),
    user_template="""\
Below are {n} customer feedback items. Read all of them carefully and identify \
the {min_categories}–{max_categories} most common, recurring topics or issues.

For each topic, return:
- key: a short snake_case identifier (lowercase, underscores, no spaces, e.g. app_stability)
- label: a short human-readable name (2–5 words)
- description: one sentence describing what belongs in this category
- examples: exactly 3 short phrases from the actual feedback that belong here

Rules:
- Every category must appear in at least 2 of the feedback items
- Categories must be mutually exclusive where possible
- Do NOT create a generic "other" or "miscellaneous" category (one will be added automatically)
- Do NOT invent topics that aren't clearly present in the data
{locked_section}
Return a JSON object with a single key "categories" containing an array of category objects.

Schema:
{{
  "categories": [
    {{
      "key": string,
      "label": string,
      "description": string,
      "examples": [string, string, string]
    }}
  ]
}}

Feedback items:
{feedback_json}
""",
)


# ─── Stage 4: Extraction ──────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """\
You are a feedback classifier for a product team.
Your only job is to classify feedback items using the provided category list.
Return only valid JSON matching the exact schema. No explanation. No extra fields.\
"""

EXTRACTION = Prompt(
    system=EXTRACTION_SYSTEM,
    user_template="""\
Classify each of the following {n} feedback items.

Available categories:
{categories_json}

For each item return:
- item_index: the integer index (0-based) of the item
- category: exactly one key from the category list above
- sentiment: one of [positive, negative, neutral, mixed]
- urgency: one of [high, medium, low]
- key_phrase: the single most important phrase from the feedback text \
(under 10 words, copied verbatim from the text, or null if unclear)
- confidence: float 0.0–1.0 representing your classification confidence

Rules:
- Use "other" only if the text genuinely doesn't fit any category
- confidence < 0.5 means you are guessing; be honest
- Do not add keys not listed in the schema

Return a JSON object with a single key "labels" containing an array of {n} label objects \
in the same order as the input items.

Schema:
{{
  "labels": [
    {{
      "item_index": int,
      "category": string,
      "sentiment": string,
      "urgency": string,
      "key_phrase": string or null,
      "confidence": float
    }}
  ]
}}

Feedback items:
{items_json}
""",
)


# ─── Stage 7: Query Engine ────────────────────────────────────────────────────

QUERY_SYSTEM = """\
You are an expert analyst helping understand user feedback.
The feedback data has been labeled with category, sentiment (positive/negative/neutral/mixed), and urgency (high/medium/low).

Your job is to:
1. Give a direct, specific 2-3 sentence answer
2. Extract 3-5 concrete, data-backed insights — each must reference specific counts, categories, or patterns. Never vague statements like "users are unhappy". Say "12 of 15 billing reports are high urgency" instead.
3. Select 3-5 representative feedback quotes that directly support the answer, with a one-sentence explanation of why each is relevant
4. Assess confidence: high = data clearly answers with many examples; medium = some relevant data but limited; low = little data matches this question

Rules:
- Answer only from the provided data — do not speculate
- If the question isn't well-addressed by the data, say so and set confidence to "low"
- Key insights must be specific and grounded in the actual items provided
- If there is a prior conversation, treat follow-up questions as continuations of that context\
"""


# ─── Stage 8: Grounded Summarization ─────────────────────────────────────────

SUMMARIZATION = Prompt(
    system=(
        "You are a product analyst writing a concise feedback summary for a product team. "
        "Use only the statistics provided. Do not invent numbers or mention issues "
        "not present in the data. Be specific and actionable. No fluff."
    ),
    user_template="""\
Write a 3-paragraph executive summary based on the following analyzed feedback data.
Reference specific numbers. Each paragraph should have a clear point.

Run: {filename}
Period: {date_range}
Total items analyzed: {total}

Top issues by volume:
{volume_summary}

Sentiment overview:
- {pct_negative}% negative, {pct_neutral}% neutral, {pct_positive}% positive

Most urgent items (high urgency count):
{urgency_summary}

Human review accuracy: {accuracy_pct}% of reviewed items confirmed LLM labels
""",
)
