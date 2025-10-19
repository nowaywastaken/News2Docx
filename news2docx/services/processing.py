from __future__ import annotations

from typing import Any, Dict, List

from news2docx.process.engine import Article as ProcArticle
from news2docx.process.engine import process_articles_two_steps_concurrent


def articles_from_json(data: Dict[str, Any]) -> List[ProcArticle]:
    """将 JSON 数据转换为处理引擎的文章列表。"""
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


def process_articles(articles: List[ProcArticle], conf: Dict[str, Any]) -> Dict[str, Any]:
    """执行两步处理流程（清洗和翻译）。"""
    return process_articles_two_steps_concurrent(
        articles, target_lang="Chinese", merge_short_chars=80
    )
