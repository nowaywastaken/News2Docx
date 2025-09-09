from __future__ import annotations
"""Configuration and data models for the scraping package."""
from dataclasses import dataclass, field, asdict
from typing import List, Dict
import os
import time

# Default configuration values
DEFAULT_REQUEST_TIMEOUT: int = 30
DEFAULT_CONCURRENCY: int = 4
DEFAULT_MAX_URLS: int = 1


@dataclass
class ScrapeConfig:
    """Configuration for :class:`~scraper.runner.NewsScraper`."""

    output_dir: str = ""
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    concurrency: int = DEFAULT_CONCURRENCY
    max_urls: int = DEFAULT_MAX_URLS


@dataclass
class Article:
    """Representation of a scraped article."""

    index: int
    url: str
    title: str
    content: str
    scraped_at: str
    word_count: int


@dataclass
class ScrapeResults:
    """Container for results returned by the scraper."""

    total: int
    success: int
    failed: int
    articles: List[Article] = field(default_factory=list)

    def to_jsonable(self) -> Dict:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "articles": [asdict(a) for a in self.articles],
        }


def now_stamp() -> str:
    """Return a timestamp suitable for filenames."""
    return time.strftime("%Y%m%d_%H%M%S")
