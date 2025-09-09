from scraper.config import Article, now_stamp
from processor.concurrency import process_articles_concurrent


def test_process_articles_concurrent_echo() -> None:
    article = Article(index=1, url="http://example.com", title="Hello", content="World", scraped_at=now_stamp(), word_count=1)
    processed = process_articles_concurrent([article])
    assert processed[0]["translated_title"].startswith("Translate to")
