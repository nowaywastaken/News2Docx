"""High level scraping orchestration."""
from __future__ import annotations
from typing import List
from .config import ScrapeConfig, Article, ScrapeResults, now_stamp
from .http_client import HttpClient
from .extractor import ContentExtractor
from processor.word_adjust import count_english_words


class NewsScraper:
    """Coordinate fetching and extracting articles from a list of URLs."""

    def __init__(self, config: ScrapeConfig) -> None:
        self.config = config
        self.client = HttpClient()
        self.extractor = ContentExtractor()

    def scrape(self, urls: List[str]) -> ScrapeResults:
        articles: List[Article] = []
        for idx, url in enumerate(urls[: self.config.max_urls], start=1):
            html = self.client.get(url, timeout=self.config.request_timeout)
            if not html:
                continue
            title, content = self.extractor.extract(html)
            word_count = count_english_words(content)
            articles.append(
                Article(
                    index=idx,
                    url=url,
                    title=title,
                    content=content,
                    scraped_at=now_stamp(),
                    word_count=word_count,
                )
            )
        total = len(urls)
        success = len(articles)
        failed = total - success
        return ScrapeResults(total=total, success=success, failed=failed, articles=articles)
