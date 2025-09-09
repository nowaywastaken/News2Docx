"""Translation helpers using a stubbed AI API."""
from __future__ import annotations
from typing import Tuple
from .prompts import TRANSLATION_SYSTEM_PROMPT, TRANSLATION_USER_PROMPT


def call_ai_api(system_prompt: str, user_prompt: str) -> str:
    """Stub for an AI API call.

    The real project uses an external service.  For testing purposes we simply
    echo the user prompt content which makes the behaviour deterministic and
    avoids external dependencies.
    """
    return user_prompt


def build_translation_prompts(text: str, target_lang: str = "Chinese") -> Tuple[str, str]:
    system_prompt = TRANSLATION_SYSTEM_PROMPT
    user_prompt = TRANSLATION_USER_PROMPT.format(language=target_lang, text=text)
    return system_prompt, user_prompt


def translate_text(text: str, target_lang: str = "Chinese") -> str:
    system_prompt, user_prompt = build_translation_prompts(text, target_lang)
    result = call_ai_api(system_prompt, user_prompt)
    return result


def translate_title(title: str, target_lang: str = "Chinese") -> str:
    return translate_text(title, target_lang)
