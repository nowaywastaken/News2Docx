"""Scraper package providing simple web scraping utilities."""
from .config import ScrapeConfig, Article, ScrapeResults

try:  # optional dependencies during testing
    from .runner import NewsScraper
    from .http_client import HttpClient
    from .extractor import ContentExtractor
except Exception:  # pragma: no cover - used when optional deps missing
    NewsScraper = HttpClient = ContentExtractor = None

__all__ = [
    "ScrapeConfig",
    "Article",
    "ScrapeResults",
    "NewsScraper",
    "HttpClient",
    "ContentExtractor",
]
