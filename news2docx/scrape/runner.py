from __future__ import annotations

import json
import os
import random
import re
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

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# Hardcoded crawler parameters (ignore config values)
# These constants define the crawler behavior regardless of external config.
_HARDCODED_MAX_URLS = 10
_HARDCODED_CONCURRENCY = 4
_HARDCODED_TIMEOUT = 10
_HARDCODED_PICK_MODE = "random"  # random | top
_HARDCODED_RANDOM_SEED: Optional[int] = None
_HARDCODED_DB_PATH = os.path.join(os.getcwd(), ".n2d_cache", "crawled.sqlite3")
# Additional noise patterns can be extended here; config.noise_patterns is ignored
_HARDCODED_NOISE_PATTERNS: List[str] = []

# Embedded domains (replace former sites file). Edit this list to curate sources.
_EMBEDDED_SITES: List[str] = [
    "time.com",
    "bloomberg.com",
    "nytimes.com",
    "ft.com",
    "theatlantic.com",
    "csmonitor.com",
    "theguardian.com",
]

# HTTP headers for GDELT calls
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; News2Docx/2.0)",
    "Accept": "application/json,text/plain,*/*",
}


def _enforce_https_url(u: Optional[str]) -> Optional[str]:
    """Return an HTTPS URL or None if not enforceable.

    - If url scheme is https: return as-is
    - If scheme is http: attempt to upgrade to https by replacing scheme
    - If scheme is missing: return None
    - Any other scheme: return None
    """
    if not u:
        return None
    try:
        pu = urlparse(u)
        if not pu.scheme:
            return None
        if pu.scheme.lower() == "https":
            return u
        if pu.scheme.lower() == "http":
            return "https://" + u.split("://", 1)[1]
        return None
    except Exception:
        return None


@dataclass
class ScrapeConfig:
    # sites_file removed in favor of embedded list
    gdelt_timespan: str = field(default_factory=lambda: os.getenv("GDELT_TIMESPAN", "7d"))
    gdelt_max_per_call: int = field(
        default_factory=lambda: (
            int(os.getenv("GDELT_MAX_PER_CALL")) if os.getenv("GDELT_MAX_PER_CALL") else 50
        )
    )
    gdelt_sort: str = field(default_factory=lambda: os.getenv("GDELT_SORT", "datedesc"))
    # The fields below are kept for backward compatibility but ignored at runtime.
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
    noise_patterns: Optional[List[str]] = None  # ignored; use hardcoded list
    # 处理阶段英文字数下限（抓取阶段预筛选），放弃上限
    required_word_min: Optional[int] = None


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
    # Enforce HTTPS for all outbound requests
    url_https = _enforce_https_url(url)
    if not url_https:
        return None
    try:
        r = requests.get(url_https, headers=headers, timeout=timeout)
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

        # Split patterns into substrings and regexes
        substrings: List[str] = []
        regexes: List[re.Pattern[str]] = []
        for p in NOISE_PATTERNS:
            try:
                ps = str(p).strip()
                if not ps:
                    continue
                if (
                    ps.startswith("/") and ps.endswith("/") and len(ps) >= 2
                ) or ps.lower().startswith("re:"):
                    body = ps[1:-1] if (ps.startswith("/") and ps.endswith("/")) else ps[3:]
                    try:
                        regexes.append(re.compile(body, flags=re.IGNORECASE))
                    except Exception:
                        # Fallback to substring if regex fails
                        substrings.append(ps)
                else:
                    substrings.append(ps)
            except Exception:
                continue

        def _is_noise(s: str) -> bool:
            t = s.strip().lower()
            if len(t) <= 20:
                return True
            for pat in substrings:
                if pat.lower() in t:
                    return True
            for rgx in regexes:
                try:
                    if rgx.search(s):
                        return True
                except Exception:
                    continue
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

    substrings: List[str] = []
    regexes: List[re.Pattern[str]] = []
    for p in NOISE_PATTERNS:
        try:
            ps = str(p).strip()
            if not ps:
                continue
            if (ps.startswith("/") and ps.endswith("/") and len(ps) >= 2) or ps.lower().startswith(
                "re:"
            ):
                body = ps[1:-1] if (ps.startswith("/") and ps.endswith("/")) else ps[3:]
                try:
                    regexes.append(re.compile(body, flags=re.IGNORECASE))
                except Exception:
                    substrings.append(ps)
            else:
                substrings.append(ps)
        except Exception:
            continue

    def _is_noise(s: str) -> bool:
        t = s.strip().lower()
        if len(t) <= 20:
            return True
        for pat in substrings:
            if pat.lower() in t:
                return True
        for rgx in regexes:
            try:
                if rgx.search(s):
                    return True
            except Exception:
                continue
        return False

    content = "\n\n".join([p for p in paras if len(p) > 20 and not _is_noise(p)])
    return title_text, content


class NewsScraper:
    def __init__(self, cfg: ScrapeConfig) -> None:
        # Copy and then override with hardcoded parameters to fully ignore external config
        self.cfg = cfg
        self.cfg.max_urls = _HARDCODED_MAX_URLS
        self.cfg.concurrency = _HARDCODED_CONCURRENCY
        self.cfg.timeout = _HARDCODED_TIMEOUT
        self.cfg.pick_mode = _HARDCODED_PICK_MODE
        self.cfg.random_seed = _HARDCODED_RANDOM_SEED
        self.cfg.db_path = _HARDCODED_DB_PATH
        self.cfg.noise_patterns = list(_HARDCODED_NOISE_PATTERNS)
        # Ensure DB directory exists
        try:
            os.makedirs(os.path.dirname(self.cfg.db_path), exist_ok=True)
        except Exception:
            pass
        # 读取字数门槛（若无则不启用抓取阶段筛选）
        try:
            mn = int(self.cfg.required_word_min) if self.cfg.required_word_min is not None else None
        except Exception:
            mn = None
        self._word_min: Optional[int] = mn

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
        # Local-only: fetch from GDELT using configured sites
        return self._fetch_urls_local_gdelt()

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
            r = requests.get(url, timeout=self.cfg.timeout, headers=_HTTP_HEADERS)
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
            u = _enforce_https_url(a.get("url"))
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _fetch_urls_local_gdelt(self) -> List[str]:
        # Build from embedded domains list
        sites: List[str] = list(_EMBEDDED_SITES)
        if not sites:
            return []

        # Batch queries to reduce 'keywords too common'
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

        target_success = max(1, int(self.cfg.max_urls))
        success_arts: List[Article] = []
        attempted_urls: set[str] = set()
        total_attempts = 0

        # 初始候选池
        pool = self._filter_new_urls(self._fetch_urls())
        # 不再用 _pick_urls 限制池大小，改为在循环中按需取批次

        # 为了避免无限循环：最多启动若干补充轮（含初始轮）
        # 这里不新增配置，采用与并发规模相关的安全上限
        max_rounds = 30
        rounds = 0

        while len(success_arts) < target_success and rounds < max_rounds:
            # 补充候选池
            if not pool:
                rounds += 1
                fresh = self._filter_new_urls(self._fetch_urls())
                # 去除本轮已尝试过的URL
                pool = [u for u in fresh if u not in attempted_urls]
                if not pool:
                    # 无可用新URL，退出
                    break

            # 按需取下一批（不超过剩余目标数与并发）
            need = target_success - len(success_arts)
            batch_size = max(1, min(int(self.cfg.concurrency), need, len(pool)))
            batch: List[str] = []
            for _ in range(batch_size):
                if not pool:
                    break
                u = pool.pop(0)
                if u in attempted_urls:
                    continue
                attempted_urls.add(u)
                batch.append(u)

            if not batch:
                # 虽然pool非空，但都被标记为已尝试；继续下一轮补充
                rounds += 1
                continue

            # 抓取该批
            with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as ex:
                futs = {
                    ex.submit(self._scrape_one, total_attempts + i + 1, u): u
                    for i, u in enumerate(batch)
                }
                for fut in as_completed(futs):
                    total_attempts += 1
                    a = fut.result()
                    if a:
                        # 抓取阶段若配置了字数区间，只累计满足要求的文章
                        try:
                            ok_wc = True
                            if self._word_min is not None:
                                ok_wc = a.word_count >= self._word_min
                            if ok_wc:
                                success_arts.append(a)
                        except Exception:
                            success_arts.append(a)
                        if len(success_arts) >= target_success:
                            break

        # 截断至目标篇数（并保持稳定顺序），并重排索引
        success_arts = success_arts[:target_success]
        try:
            for i, a in enumerate(success_arts, start=1):
                a.index = i  # type: ignore[attr-defined]
        except Exception:
            pass
        failed_count = max(0, total_attempts - len(success_arts))

        res = ScrapeResults(
            total=total_attempts,
            success=len(success_arts),
            failed=failed_count,
            articles=success_arts,
        )

        # 仅标记成功的URL，失败不入库以便后续机会重试
        try:
            self._mark_crawled_bulk([a.url for a in success_arts])
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
