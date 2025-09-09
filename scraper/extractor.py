"""HTML content extraction helpers."""
from __future__ import annotations
from typing import Tuple
from bs4 import BeautifulSoup


class ContentExtractor:
    """Extract title and text content from HTML pages."""

    def extract(self, html: str) -> Tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        content = "\n".join(paragraphs)
        return title, content
