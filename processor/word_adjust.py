"""Utilities for word counting and adjustment calculations."""
from __future__ import annotations
import re


def count_english_words(text: str) -> int:
    """Count the number of word tokens in ``text``.

    The implementation removes HTML tags and punctuation so that the count is
    stable for unit tests and simple analyses.
    """
    if not text:
        return 0
    text = re.sub(r"<[^>]+>", "", text)
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def calculate_word_adjustment_percentage(
    current_words: int, target_min: int = 400, target_max: int = 450
) -> float:
    """Return percentage of words to add (positive) or remove (negative)."""
    if target_min <= current_words <= target_max:
        return 0.0
    target_center = (target_min + target_max) / 2
    if current_words < target_min:
        deficit = target_center - current_words
        percentage = (deficit / current_words) * 100
    else:
        excess = current_words - target_center
        percentage = -(excess / current_words) * 100
    return round(percentage, 2)
