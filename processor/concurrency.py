"""Concurrency helpers for processing articles."""
from __future__ import annotations
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from scraper.config import Article
from .translation import translate_title, translate_text


def _process_single(article: Article, target_lang: str) -> Dict[str, Any]:
    translated_title = translate_title(article.title, target_lang)
    translated_content = translate_text(article.content, target_lang)
    return {
        "id": article.index,
        "url": article.url,
        "original_title": article.title,
        "original_content": article.content,
        "translated_title": translated_title,
        "translated_content": translated_content,
        "word_count": article.word_count,
    }


def process_articles_concurrent(
    articles: List[Article], target_lang: str = "Chinese"
) -> List[Dict[str, Any]]:
    """Translate ``articles`` concurrently and return processed dictionaries."""
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(_process_single, a, target_lang) for a in articles]
        return [f.result() for f in futures]
