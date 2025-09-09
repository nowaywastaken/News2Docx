from __future__ import annotations

import os
import time
import json
import random
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
import sqlite3
from bs4 import BeautifulSoup
from news2docx.scrape.selectors import load_selector_overrides, merge_selectors

from news2docx.core.utils import now_stamp
from news2docx.infra.logging import unified_print, log_task_start, log_task_end, log_processing_step


DEFAULT_CRAWLER_API_URL = "https://gdelt-xupojkickl.cn-hongkong.fcapp.run"


@dataclass
class ScrapeConfig:
    api_url: str = os.getenv("CRAWLER_API_URL", DEFAULT_CRAWLER_API_URL)
    api_token: Optional[str] = field(default_factory=lambda: os.getenv("CRAWLER_API_TOKEN"))
    timeout: int = 30
    concurrency: int = 4
    max_urls: int = 1
    pick_mode: str = field(default_factory=lambda: os.getenv("CRAWLER_PICK_MODE", "random"))
    random_seed: Optional[int] = field(default_factory=lambda: (int(os.getenv("CRAWLER_RANDOM_SEED")) if os.getenv("CRAWLER_RANDOM_SEED") else None))
    db_path: str = field(default_factory=lambda: os.getenv("N2D_DB_PATH", os.path.join(os.getcwd(), ".n2d_cache", "crawled.sqlite3")))
    noise_patterns: Optional[List[str]] = None  # extra noise patterns from config


@dataclass
class Article:
    index: int
    url: str
    title: str
    content: str
    content_length: int
    word_count: int
    scraped_at: str


@dataclass
class ScrapeResults:
    total: int
    success: int
    failed: int
    articles: List[Article] = field(default_factory=list)


def _http_post(url: str, json_body: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Optional[Dict[str, Any]]:
    try:
        r = requests.post(url, json=json_body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json() if r.content else {}
    except Exception:
        return None


def _http_get_text(url: str, headers: Dict[str, str], timeout: int) -> Optional[str]:
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"
        return r.text
    except Exception:
        return None


def _extract(html: str, url: str, noise_patterns: Optional[List[str]] = None) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    netloc = urlparse(url).netloc.lower()

    # baseline selectors + optional overrides
    base = {
        "bbc.com": {
            "title": ['h1[data-testid="headline"]', "h1"],
            "content": ['[data-component="text-block"] p', 'article p', 'p'],
            "remove": [".ad", "script", "style", "nav", "aside"],
        },
        "cnn.com": {
            "title": ["h1.headline__text", "h1"],
            "content": ['div[data-module="ArticleBody"] p', '.article__content p', 'p'],
            "remove": [".ad", ".byline", "script", "style"],
        },
        "nytimes.com": {
            "title": ['h1[data-testid="headline"]', 'h1'],
            "content": ['section[name="articleBody"] p', 'div[data-testid="articleBody"] p', 'p'],
            "remove": [".css-1cp3ece", ".byline", "script", "style"],
        },
        "time.com": {
            "title": ["h1.headline", "h1"],
            "content": ['div[data-testid="article-body"] p', 'article p', 'p'],
            "remove": [".ad", ".tags", "script", "style"],
        },
    }
    try:
        cfg_path = os.getenv("SCRAPER_SELECTORS_FILE")
        if cfg_path:
            base = merge_selectors(base, load_selector_overrides(cfg_path))
    except Exception:
        pass

    # pick domain key
    key = next((k for k in base.keys() if k in netloc), None)
    if key:
        for sel in base[key].get("remove", []):
            try:
                for el in soup.select(sel):
                    el.decompose()
            except Exception:
                pass
        # title
        title_text = ""
        for sel in base[key].get("title", []):
            try:
                node = soup.select_one(sel)
                if node:
                    t = node.get_text(strip=True)
                    if t:
                        title_text = t
                        break
            except Exception:
                continue
        if not title_text:
            title_text = (soup.title.get_text(strip=True) if soup.title else "")
        # content
        paras: List[str] = []
        for sel in base[key].get("content", []):
            try:
                nodes = soup.select(sel)
                for n in nodes:
                    txt = n.get_text(strip=True)
                    if len(txt) >= 30 and len(txt.split()) >= 5:
                        paras.append(txt)
                if paras:
                    break
            except Exception:
                continue
        if not paras:
            paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) >= 30]
        # Heuristic noise filtering: drop login/cookie/notice banners
        NOISE_PATTERNS = (noise_patterns or [])
        def _is_noise(s: str) -> bool:
            t = s.strip().lower()
            if len(t) <= 20:
                return True
            for pat in NOISE_PATTERNS:
                if pat.lower() in t:
                    return True
            return False
        filtered = [x for x in paras if not _is_noise(x)]
        content = "\n\n".join(filtered or paras)
        return title_text, content

    # fallback generic
    title = soup.find("h1")
    title_text = title.get_text(strip=True) if title else (soup.title.get_text(strip=True) if soup.title else "")
    paras = [p.get_text(strip=True) for p in soup.find_all("p")]
    # Apply same noise filtering for generic fallback
    NOISE_PATTERNS = (noise_patterns or [])
    def _is_noise(s: str) -> bool:
        t = s.strip().lower()
        if len(t) <= 20:
            return True
        for pat in NOISE_PATTERNS:
            if pat.lower() in t:
                return True
        return False
    content = "\n\n".join([p for p in paras if len(p) > 20 and not _is_noise(p)])
    return title_text, content


class NewsScraper:
    def __init__(self, cfg: ScrapeConfig) -> None:
        if not cfg.api_token:
            raise ValueError("CRAWLER_API_TOKEN is required")
        self.cfg = cfg
        # Ensure DB directory exists
        try:
            os.makedirs(os.path.dirname(self.cfg.db_path), exist_ok=True)
        except Exception:
            pass

    # ---------------- DB helpers ----------------
    def _db_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.cfg.db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS crawled_urls (url TEXT PRIMARY KEY, scraped_at TEXT)")
        return conn

    def _filter_new_urls(self, urls: List[str]) -> List[str]:
        if not urls:
            return []
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            out: List[str] = []
            for u in urls:
                cur.execute("SELECT 1 FROM crawled_urls WHERE url=? LIMIT 1", (u,))
                if cur.fetchone() is None:
                    out.append(u)
            conn.close()
            return out
        except Exception:
            return urls

    def _mark_crawled_bulk(self, urls: List[str]) -> None:
        if not urls:
            return
        try:
            conn = self._db_connect()
            cur = conn.cursor()
            now = now_stamp()
            cur.executemany("INSERT OR IGNORE INTO crawled_urls(url, scraped_at) VALUES(?, ?)", [(u, now) for u in urls])
            conn.commit()
            conn.close()
        except Exception:
            pass

    # --------------- URL picking ---------------
    def _pick_urls(self, urls: List[str]) -> List[str]:
        if not urls:
            return []
        mode = (self.cfg.pick_mode or "random").lower()
        maxn = max(1, int(self.cfg.max_urls))
        pool = list(urls)
        if mode == "random":
            try:
                if self.cfg.random_seed is not None:
                    random.seed(self.cfg.random_seed)
                random.shuffle(pool)
            except Exception:
                pass
        # else: keep original order
        return pool[:maxn]

    def _fetch_urls(self) -> List[str]:
        headers = {
            "Authorization": f"Bearer {self.cfg.api_token}",
            "Content-Type": "application/json",
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            ]),
        }
        data = _http_post(self.cfg.api_url, {}, headers, self.cfg.timeout) or {}
        urls = data.get("urls") if isinstance(data, dict) else data
        if not isinstance(urls, list):
            return []
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]

    def _noise_patterns(self) -> List[str]:
        base = [
            "please refresh", "refresh your browser", "auto login", "automatic login", "sign in", "sign up",
            "subscribe", "newsletter", "cookie", "cookies", "privacy", "terms", "ad choices", "manage settings",
            "enable cookies", "your browser settings", "consent",
        ]
        extra = self.cfg.noise_patterns or []
        try:
            return base + list(extra)
        except Exception:
            return base

    def _scrape_one(self, idx: int, url: str) -> Optional[Article]:
        html = _http_get_text(url, {"User-Agent": "Mozilla/5.0"}, self.cfg.timeout)
        if not html:
            return None
        title, content = _extract(html, url, self._noise_patterns())
        if not title or not content:
            return None
        wc = len(content.split())
        return Article(index=idx, url=url, title=title, content=content, content_length=len(content), word_count=wc, scraped_at=now_stamp())

    def run(self) -> ScrapeResults:
        log_task_start("scrape", "run", {"max_urls": self.cfg.max_urls, "concurrency": self.cfg.concurrency})
        urls_all = self._fetch_urls()
        # filter previously crawled
        urls_new = self._filter_new_urls(urls_all)
        # pick subset (random or top)
        urls = self._pick_urls(urls_new)
        if not urls:
            return ScrapeResults(total=0, success=0, failed=0, articles=[])
        arts: List[Article] = []
        with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as ex:
            futs = {ex.submit(self._scrape_one, i + 1, u): u for i, u in enumerate(urls)}
            for fut in as_completed(futs):
                a = fut.result()
                if a:
                    arts.append(a)
        res = ScrapeResults(total=len(urls), success=len(arts), failed=len(urls) - len(arts), articles=arts)
        # mark successfully scraped URLs into DB to avoid re-crawling
        try:
            self._mark_crawled_bulk([a.url for a in arts])
        except Exception:
            pass
        log_task_end("scrape", "run", True, asdict(res))
        return res


def save_scraped_data_to_json(results: ScrapeResults, timestamp: str) -> str:
    payload = {
        "metadata": {
            "total_articles": results.total,
            "successful_articles": results.success,
            "failed_articles": results.failed,
            "scraped_at": timestamp,
            "scraper_version": "2.0.0",
        },
        "articles": [asdict(a) for a in results.articles],
    }
    fn = f"scraped_news_{timestamp}.json"
    open(fn, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))
    unified_print(f"scrape saved: {fn}", "scrape", "save")
    return fn
