from __future__ import annotations

import json
import os
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from news2docx.core.utils import now_stamp
from news2docx.infra.logging import log_task_end, log_task_start, unified_print
from news2docx.scrape.selectors import load_selector_overrides, merge_selectors

DEFAULT_CRAWLER_API_URL = "https://gdelt-xupojkickl.cn-hongkong.fcapp.run"
GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass
class ScrapeConfig:
    api_url: str = os.getenv("CRAWLER_API_URL", DEFAULT_CRAWLER_API_URL)
    api_token: Optional[str] = field(default_factory=lambda: os.getenv("CRAWLER_API_TOKEN"))
    mode: str = field(default_factory=lambda: os.getenv("CRAWLER_MODE", "remote"))  # remote | local
    sites_file: Optional[str] = field(
        default_factory=lambda: os.getenv("CRAWLER_SITES_FILE")
        or os.path.join(os.getcwd(), "server", "news_website.txt")
    )
    gdelt_timespan: str = field(default_factory=lambda: os.getenv("GDELT_TIMESPAN", "7d"))
    gdelt_max_per_call: int = field(
        default_factory=lambda: (
            int(os.getenv("GDELT_MAX_PER_CALL")) if os.getenv("GDELT_MAX_PER_CALL") else 50
        )
    )
    gdelt_sort: str = field(default_factory=lambda: os.getenv("GDELT_SORT", "datedesc"))
    timeout: int = 30
    concurrency: int = 4
    max_urls: int = 1
    pick_mode: str = field(default_factory=lambda: os.getenv("CRAWLER_PICK_MODE", "random"))
    random_seed: Optional[int] = field(
        default_factory=lambda: (
            int(os.getenv("CRAWLER_RANDOM_SEED")) if os.getenv("CRAWLER_RANDOM_SEED") else None
        )
    )
    db_path: str = field(
        default_factory=lambda: os.getenv(
            "N2D_DB_PATH", os.path.join(os.getcwd(), ".n2d_cache", "crawled.sqlite3")
        )
    )
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


def _http_post(
    url: str, json_body: Dict[str, Any], headers: Dict[str, str], timeout: int
) -> Optional[Dict[str, Any]]:
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
            "content": ['[data-component="text-block"] p', "article p", "p"],
            "remove": [".ad", "script", "style", "nav", "aside"],
        },
        "cnn.com": {
            "title": ["h1.headline__text", "h1"],
            "content": ['div[data-module="ArticleBody"] p', ".article__content p", "p"],
            "remove": [".ad", ".byline", "script", "style"],
        },
        "nytimes.com": {
            "title": ['h1[data-testid="headline"]', "h1"],
            "content": ['section[name="articleBody"] p', 'div[data-testid="articleBody"] p', "p"],
            "remove": [".css-1cp3ece", ".byline", "script", "style"],
        },
        "time.com": {
            "title": ["h1.headline", "h1"],
            "content": ['div[data-testid="article-body"] p', "article p", "p"],
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
            title_text = soup.title.get_text(strip=True) if soup.title else ""
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
            paras = [
                p.get_text(strip=True)
                for p in soup.find_all("p")
                if len(p.get_text(strip=True)) >= 30
            ]
        # Heuristic noise filtering: drop login/cookie/notice banners
        NOISE_PATTERNS = noise_patterns or []

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
    title_text = (
        title.get_text(strip=True)
        if title
        else (soup.title.get_text(strip=True) if soup.title else "")
    )
    paras = [p.get_text(strip=True) for p in soup.find_all("p")]
    # Apply same noise filtering for generic fallback
    NOISE_PATTERNS = noise_patterns or []

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
        mode = (cfg.mode or "remote").lower()
        if mode == "remote" and not cfg.api_token:
            raise ValueError("CRAWLER_API_TOKEN is required in remote mode")
        # Enforce HTTPS for remote crawler endpoint
        if mode == "remote":
            try:
                from urllib.parse import urlparse

                pu = urlparse(str(cfg.api_url or ""))
                if pu.scheme.lower() != "https":
                    raise ValueError(
                        f"安全策略：crawler_api_url 必须为 https，当前为：{cfg.api_url}"
                    )
            except Exception:
                raise
        self.cfg = cfg
        # Ensure DB directory exists
        try:
            os.makedirs(os.path.dirname(self.cfg.db_path), exist_ok=True)
        except Exception:
            pass

    # ---------------- DB helpers ----------------
    def _db_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.cfg.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crawled_urls (url TEXT PRIMARY KEY, scraped_at TEXT)"
        )
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
            cur.executemany(
                "INSERT OR IGNORE INTO crawled_urls(url, scraped_at) VALUES(?, ?)",
                [(u, now) for u in urls],
            )
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
        mode = (self.cfg.mode or "remote").lower()
        if mode == "local":
            return self._fetch_urls_local_gdelt()
        headers = {
            "Authorization": f"Bearer {self.cfg.api_token}",
            "Content-Type": "application/json",
            "User-Agent": random.choice(
                [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
                ]
            ),
        }
        data = _http_post(self.cfg.api_url, {}, headers, self.cfg.timeout) or {}
        urls = data.get("urls") if isinstance(data, dict) else data
        if not isinstance(urls, list):
            return []
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]

    # -------- Local GDELT mode --------
    def _gdelt_build_query(self, sites: List[str]) -> str:
        parts = [f"domainis:{d}" for d in sites if d]
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"

    def _gdelt_request(self, query: str) -> dict:
        params = {
            "mode": "ArtList",
            "format": "json",
            "sort": self.cfg.gdelt_sort,
            "timespan": self.cfg.gdelt_timespan,
            "query": query,
            "maxrecords": int(self.cfg.gdelt_max_per_call),
        }
        url = f"{GDELT_BASE}?{urlencode(params)}"
        try:
            r = requests.get(url, timeout=self.cfg.timeout, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            # ensure JSON-ish
            ct = (r.headers.get("Content-Type") or "").lower()
            if "json" not in ct:
                return {}
            return r.json()
        except Exception:
            return {}

    def _gdelt_extract_urls(self, raw_json: dict, lang: str = "eng") -> List[str]:
        arts = (raw_json or {}).get("articles", []) or []
        seen, out = set(), []
        want = (lang or "eng").strip().lower()
        english_aliases = {"english", "en", "eng"}
        wanted_set = english_aliases if want in english_aliases else {want}
        for a in arts:
            lv = (a.get("language") or "").strip().lower()
            if lv not in wanted_set:
                continue
            u = a.get("url")
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _fetch_urls_local_gdelt(self) -> List[str]:
        # read sites
        sites: List[str] = []
        try:
            with open(self.cfg.sites_file, "r", encoding="utf-8") as f:
                for ln in f:
                    s = (ln or "").strip()
                    if s and not s.startswith("#"):
                        sites.append(s)
        except Exception:
            pass
        if not sites:
            return []

        # batch queries to reduce 'keywords too common'
        batch_size = 5
        all_urls: List[str] = []
        seen = set()
        for i in range(0, len(sites), batch_size):
            batch = sites[i : i + batch_size]
            q = self._gdelt_build_query(batch)
            data = self._gdelt_request(q)
            urls = self._gdelt_extract_urls(data, lang="eng")
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    all_urls.append(u)
        return all_urls

    def _noise_patterns(self) -> List[str]:
        base = [
            "please refresh",
            "refresh your browser",
            "auto login",
            "automatic login",
            "sign in",
            "sign up",
            "subscribe",
            "newsletter",
            "cookie",
            "cookies",
            "privacy",
            "terms",
            "ad choices",
            "manage settings",
            "enable cookies",
            "your browser settings",
            "consent",
            # Common site boilerplate
            "Posts from this author will be added",
            "Posts from this topic will be added",
            "A free daily digest of the news that matters most",
            "This is the title for the native ad",
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
        return Article(
            index=idx,
            url=url,
            title=title,
            content=content,
            content_length=len(content),
            word_count=wc,
            scraped_at=now_stamp(),
        )

    def run(self) -> ScrapeResults:
        log_task_start(
            "scrape", "run", {"max_urls": self.cfg.max_urls, "concurrency": self.cfg.concurrency}
        )
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
        res = ScrapeResults(
            total=len(urls), success=len(arts), failed=len(urls) - len(arts), articles=arts
        )
        # mark successfully scraped URLs into DB to avoid re-crawling
        try:
            self._mark_crawled_bulk([a.url for a in arts])
        except Exception:
            pass
        log_task_end("scrape", "run", True, asdict(res))
        return res


def save_scraped_data_to_json(results: ScrapeResults, timestamp: str) -> str:
    """Save scraped payload under runs/<timestamp>/scraped.json for unified run layout.

    Returns absolute or relative path to the saved JSON.
    """
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
    try:
        from news2docx.services.runs import runs_base_dir

        base = runs_base_dir()
        run_dir = Path(base) / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_dir / "scraped.json"
    except Exception:
        out_path = Path(f"scraped_news_{timestamp}.json")
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    unified_print(f"scrape saved: {out_path}", "scrape", "save")
    return str(out_path)
