"""Prompt templates used by the processor package."""
from __future__ import annotations

TRANSLATION_SYSTEM_PROMPT: str = (
    "You are a helpful translator. Return only the translated text."
)
TRANSLATION_USER_PROMPT: str = "Translate to {language}:\n\n{text}"
