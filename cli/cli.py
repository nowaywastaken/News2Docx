"""Command line interface for the News2Docx project."""
from __future__ import annotations
import argparse
from typing import List

from scraper import ScrapeConfig, NewsScraper
from processor import process_articles_concurrent


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple news scraper and translator")
    parser.add_argument("urls", nargs="+", help="URLs to scrape")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
    config = ScrapeConfig()
    scraper = NewsScraper(config)
    results = scraper.scrape(args.urls)
    processed = process_articles_concurrent(results.articles)
    for article in processed:
        print(f"# {article['translated_title']}")
        print(article["translated_content"])


if __name__ == "__main__":  # pragma: no cover
    main()
