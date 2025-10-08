from __future__ import annotations

from typing import Any, Dict, List, Optional

from news2docx.process.engine import (
    Article as ProcArticle,
)
from news2docx.process.engine import (
    process_articles_two_steps_concurrent,
)


def articles_from_json(data: Dict[str, Any]) -> List[ProcArticle]:
    """Convert JSON dict (scraped) into engine ProcArticle list."""
    raw = data.get("articles", []) if isinstance(data, dict) else []
    arts: List[ProcArticle] = []
    for a in raw:
        try:
            idx = int(a.get("id") or a.get("index") or 0)
        except Exception:
            idx = 0
        arts.append(
            ProcArticle(
                index=idx,
                url=a.get("url", ""),
                title=a.get("title", ""),
                content=a.get("content", ""),
                content_length=int(a.get("content_length", 0) or 0),
                word_count=int(a.get("words", 0) or a.get("word_count", 0) or 0),
            )
        )
    return arts


def articles_from_scraped(objs: List[object]) -> List[ProcArticle]:
    """Convert scrape.runner.Article list into engine ProcArticle list."""
    arts: List[ProcArticle] = []
    for a in objs or []:
        try:
            idx = int(getattr(a, "index", 0) or 0)
        except Exception:
            idx = 0
        arts.append(
            ProcArticle(
                index=idx,
                url=getattr(a, "url", ""),
                title=getattr(a, "title", ""),
                content=getattr(a, "content", ""),
                content_length=int(getattr(a, "content_length", 0) or 0),
                word_count=int(getattr(a, "word_count", 0) or 0),
            )
        )
    return arts


def process_articles(articles: List[ProcArticle], conf: Dict[str, Any]) -> Dict[str, Any]:
    """Run the two-step processing with config-derived options."""
    target_lang = (
        (conf.get("target_language") or "Chinese") if isinstance(conf, dict) else "Chinese"
    )
    merge_short = conf.get("merge_short_paragraph_chars") if isinstance(conf, dict) else None
    try:
        merge_short_i: Optional[int] = int(merge_short) if merge_short is not None else None
    except Exception:
        merge_short_i = None
    return process_articles_two_steps_concurrent(
        articles, target_lang=target_lang, merge_short_chars=merge_short_i
    )
