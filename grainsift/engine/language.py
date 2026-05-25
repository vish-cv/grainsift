"""
Language translation helper.

Translates non-English feedback to English using deep-translator (GoogleTranslator).
Designed to be best-effort: any failure logs a warning and returns None so ingest
is never blocked by a translation error.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def translate_to_english(text: str, source_language: str) -> str | None:
    """
    Translate `text` from `source_language` to English.
    Returns the translated string, or None if translation fails or is unavailable.
    """
    try:
        from deep_translator import GoogleTranslator  # lazy import — optional dep
        translated: str = GoogleTranslator(source=source_language, target="en").translate(text)
        return translated
    except Exception as exc:  # noqa: BLE001
        logger.warning("Translation failed (lang=%s): %s", source_language, exc)
        return None
