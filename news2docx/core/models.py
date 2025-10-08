from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class ArticleRaw:
    index: int
    url: str
    title: str
    content: str
    content_length: int = 0
    word_count: int = 0
    scraped_at: str = field(default_factory=lambda: time.strftime("%Y%m%d_%H%M%S"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArticleProcessed:
    id: str
    url: str
    original_title: str
    translated_title: str
    original_content: str
    adjusted_content: str
    translated_content: str
    adjusted_word_count: int
    processing_timestamp: str
    target_language: str = "Chinese"
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeResult:
    total: int
    success: int
    failed: int
    articles: List[ArticleRaw] = field(default_factory=list)
    successful_urls: List[str] = field(default_factory=list)
    failed_urls: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "articles": [a.to_dict() for a in self.articles],
            "successful_urls": list(self.successful_urls),
            "failed_urls": list(self.failed_urls),
        }
