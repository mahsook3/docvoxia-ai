"""
tools/translation_tools.py
---------------------------
ADK-compatible tool wrapping Google Cloud Translation API v3.

Exposed tool:
  - translate_text : translate a string to a target language
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "docvoxia")
LOCATION   = os.environ.get("GCP_LOCATION", "global")

# Lazy client
_translate_client = None


def _get_client():
    global _translate_client
    if _translate_client is None:
        from google.cloud import translate_v3 as translate
        _translate_client = translate.TranslationServiceClient()
    return _translate_client


def translate_text(
    text: str,
    target_language_code: str,
    source_language_code: Optional[str] = None,
) -> dict:
    """
    Translate text to the target language using Google Cloud Translation API v3.

    Args:
        text:                 The text content to translate.
        target_language_code: BCP-47 language code for the target language
                              (e.g. "ta" for Tamil, "hi" for Hindi, "fr" for French).
        source_language_code: Optional BCP-47 source language code.
                              If omitted, the API auto-detects the source language.

    Returns:
        A dict with keys:
          - "translated_text"        : str  — the translated string
          - "detected_language_code" : str  — source language detected (or provided)
          - "target_language_code"   : str  — the requested target language
    """
    if not text or not text.strip():
        return {
            "translated_text": "",
            "detected_language_code": source_language_code or "",
            "target_language_code": target_language_code,
        }

    # If source == target, skip API round-trip
    if source_language_code and source_language_code == target_language_code:
        return {
            "translated_text": text,
            "detected_language_code": source_language_code,
            "target_language_code": target_language_code,
        }

    try:
        client  = _get_client()
        parent  = f"projects/{PROJECT_ID}/locations/{LOCATION}"

        kwargs: dict = {
            "parent": parent,
            "contents": [text],
            "mime_type": "text/plain",
            "target_language_code": target_language_code,
        }
        if source_language_code:
            kwargs["source_language_code"] = source_language_code

        response = client.translate_text(**kwargs)

        translation = response.translations[0]
        detected    = (
            translation.detected_language_code
            or source_language_code
            or "unknown"
        )

        return {
            "translated_text":        translation.translated_text,
            "detected_language_code": detected,
            "target_language_code":   target_language_code,
        }

    except Exception as exc:
        logger.exception("Translation error: %s", exc)
        # Graceful degradation — return original text with error note
        return {
            "translated_text":        text,
            "detected_language_code": source_language_code or "unknown",
            "target_language_code":   target_language_code,
            "error":                  str(exc),
        }