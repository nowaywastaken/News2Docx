"""Processing package for translation and word adjustment."""
from .prompts import TRANSLATION_SYSTEM_PROMPT, TRANSLATION_USER_PROMPT
from .translation import translate_text, translate_title
from .word_adjust import count_english_words, calculate_word_adjustment_percentage
from .concurrency import process_articles_concurrent

__all__ = [
    "TRANSLATION_SYSTEM_PROMPT",
    "TRANSLATION_USER_PROMPT",
    "translate_text",
    "translate_title",
    "count_english_words",
    "calculate_word_adjustment_percentage",
    "process_articles_concurrent",
]
