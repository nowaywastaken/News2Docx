#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻爬虫主程序 - 纯爬虫模式
仅包含爬虫和解析功能，不包含AI处理
"""

import sys
import os
import re
import json
import time
import uuid
import random
import logging
import argparse
import itertools
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from urllib.parse import urlparse
from pathlib import Path

# 标准库导入
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# 统一日志系统导入
from unified_logger import (
    get_unified_logger, log_task_start, log_task_end,
    log_processing_step, log_error, log_performance,
    unified_print, log_processing_result, log_article_processing,
    log_api_call, log_file_operation, log_batch_processing
)

from utils.text import now_stamp, count_english_words, safe_filename


# -------------------------------
# 常量和配置定义
# -------------------------------

# API配置
DEFAULT_CRAWLER_API_URL = "https://gdelt-xupojkickl.cn-hongkong.fcapp.run"
DEFAULT_CRAWLER_API_TOKEN = "token-7eiac9018c346ge9c93ef25266ai"

# 文件和路径配置
DEFAULT_OUTPUT_DIR = ""
DEFAULT_SCRAPED_URLS_FILE = "scraped_urls.json"
DEFAULT_FAILED_URLS_FILE = "failed_urls.json"

# 爬虫配置
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_CONCURRENCY_SCRAPER = 4
DEFAULT_MAX_URLS = 1
DEFAULT_RETRY_INTERVAL_HOURS = 24
DEFAULT_PER_URL_RETRIES = 2
DEFAULT_MAX_API_ROUNDS = 5

SEPARATOR_LINE = "—" * 50
MAIN_SEPARATOR = "=" * 60


# -------------------------------
# 统一异常处理
# -------------------------------

class NewsProcessingError(Exception):
    """新闻处理相关异常基类"""
    pass


class ScrapingError(NewsProcessingError):
    """爬虫相关异常"""
    pass


class APIError(NewsProcessingError):
    """API相关异常"""
    pass


def handle_error(error: Exception, context: str = "", program: str = "scraper", task_type: str = "scraping") -> None:
    """
    统一错误处理函数

    Args:
        error: 异常对象
        context: 错误上下文描述
        program: 程序名称
        task_type: 任务类型
    """
    log_error(program, task_type, error, context)


def safe_execute(func, *args, error_msg: str = "执行失败", **kwargs):
    """
    安全执行函数，统一异常处理

    Args:
        func: 要执行的函数
        *args: 函数参数
        error_msg: 错误消息前缀
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果，如果失败返回None
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"❌ {error_msg}: {e}")
        return None


@dataclass
class ScrapeConfig:
    """新闻爬虫配置类"""
    output_dir: str = DEFAULT_OUTPUT_DIR
    api_url: str = os.getenv("CRAWLER_API_URL", DEFAULT_CRAWLER_API_URL)
    api_token: str = os.getenv("CRAWLER_API_TOKEN", DEFAULT_CRAWLER_API_TOKEN)
    scraped_urls_file: str = DEFAULT_SCRAPED_URLS_FILE
    failed_urls_file: str = DEFAULT_FAILED_URLS_FILE
    retry_interval_hours: int = DEFAULT_RETRY_INTERVAL_HOURS
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    concurrency: int = DEFAULT_CONCURRENCY_SCRAPER
    max_urls: int = DEFAULT_MAX_URLS

    # UA 轮换（用于降低被动封爬概率）
    user_agents: List[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ])

    # 成功数控制与重试
    strict_success: bool = True
    max_api_rounds: int = DEFAULT_MAX_API_ROUNDS
    per_url_retries: int = DEFAULT_PER_URL_RETRIES

    # URL 选取模式与随机种子
    pick_mode: str = os.getenv("CRAWLER_PICK_MODE", "random")
    random_seed: Optional[int] = (
        int(os.getenv("CRAWLER_RANDOM_SEED")) if os.getenv("CRAWLER_RANDOM_SEED") else None
    )


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
    successful_urls: List[str] = field(default_factory=list)
    failed_urls: List[str] = field(default_factory=list)

    def to_jsonable(self) -> Dict:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "articles": [asdict(a) for a in self.articles],
            "successful_urls": list(self.successful_urls),
            "failed_urls": list(self.failed_urls),
        }


def ensure_directory(path: Union[str, Path]) -> Path:
    """确保目录存在"""
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


class HttpClient:
    """HTTP客户端类，负责网络请求"""
    def __init__(self, cfg: ScrapeConfig):
        self.cfg = cfg
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        """构建HTTP会话"""
        s = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        })
        return s

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: Optional[int] = None) -> Optional[str]:
        """发送GET请求"""
        try:
            resp = self.session.get(url, headers=headers, timeout=timeout or self.cfg.request_timeout)
            resp.raise_for_status()
            enc = resp.apparent_encoding or resp.encoding or "utf-8"
            resp.encoding = enc
            return resp.text
        except requests.RequestException as e:
            handle_error(e, f"HTTP GET请求失败: {url}")
            return None

    def post(self, url: str, json_data: Dict, headers: Optional[Dict[str, str]] = None, timeout: Optional[int] = None) -> Optional[Dict]:
        """发送POST请求"""
        try:
            resp = self.session.post(url, json=json_data, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            handle_error(e, f"HTTP POST请求失败: {url}")
            return None


class ContentExtractor:
    """内容提取器类，负责解析网页内容"""
    def __init__(self, cfg: ScrapeConfig):
        self.cfg = cfg
        self.site_selectors = self._build_site_selectors()

    def _build_site_selectors(self) -> Dict[str, Dict[str, List[str]]]:
        """构建站点选择器配置"""
        return {
            "bbc.com": {
                "title": [
                    'h1[data-testid="headline"]',
                    "h1.sc-518485e5-0",
                    "h1",
                    "[data-testid=\"headline\"]",
                    ".bbc-1seqhyp",
                ],
                "content": [
                    '[data-component="text-block"]',
                    ".ssrcss-uf6wea-RichTextComponentWrapper",
                    ".bbc-19j92fr",
                    'div[data-component="text-block"] p',
                    ".story-body p",
                ],
                "remove": [
                    ".media-caption",
                    ".story-date",
                    ".byline",
                    "aside",
                    "nav",
                    ".related-links",
                ],
            },
            "cnn.com": {
                "title": [
                    "h1.headline__text",
                    'h1[data-editable="headlineText"]',
                    "h1.pg-headline",
                    "h1",
                    ".headline__text",
                ],
                "content": [
                    ".article__content p",
                    ".zn-body__paragraph",
                    'div[data-module="ArticleBody"] p',
                    ".pg-rail-tall__body p",
                    'section[data-module="ArticleBody"] p',
                ],
                "remove": [
                    ".ad",
                    ".zn-ads",
                    ".byline",
                    ".timestamp",
                    ".related-content",
                    "aside",
                    "nav",
                ],
            },
            "nytimes.com": {
                "title": [
                    'h1[data-testid="headline"]',
                    "h1.css-1w9q5pw",
                    "h1.e1h9rw200",
                    "h1",
                    ".headline",
                ],
                "content": [
                    'section[name="articleBody"] p',
                    ".StoryBodyCompanionColumn p",
                    'div[data-testid="articleBody"] p',
                    ".css-53u6y8 p",
                    "section p",
                ],
                "remove": [
                    ".css-1cp3ece",
                    ".byline",
                    ".timestamp",
                    "aside",
                    "nav",
                    ".related-coverage",
                ],
            },
            "theverge.com": {
                "title": [
                    "h1.duet--article--article-title",
                    'h1[data-testid="title"]',
                    "h1.c-page-title",
                    "h1",
                    ".duet--article--article-title",
                ],
                "content": [
                    ".duet--article--article-body p",
                    'div[data-testid="ArticleBodyWrapper"] p',
                    ".c-entry-content p",
                    ".article-body p",
                    "div.duet--article--article-body p",
                ],
                "remove": [
                    ".duet--article--article-meta",
                    ".byline",
                    ".timestamp",
                    "aside",
                    "nav",
                    ".related",
                ],
            },
            "wired.com": {
                "title": [
                    'h1[data-testid="ContentHeaderHed"]',
                    "h1.content-header__hed",
                    "h1.post-title",
                    "h1",
                    ".ContentHeaderHed",
                ],
                "content": [
                    'div[data-testid="ArticleBodyWrapper"] p',
                    ".article-body p",
                    ".content p",
                    ".post-content p",
                    "div.article__body p",
                ],
                "remove": [
                    ".byline",
                    ".publish-date",
                    ".article-tags",
                    "aside",
                    "nav",
                    ".related-articles",
                ],
            },
            "time.com": {
                "title": [
                    "h1.headline",
                    'h1[data-testid="headline"]',
                    "h1.entry-title",
                    "h1",
                    ".headline",
                ],
                "content": [
                    'div[data-testid="article-body"] p',
                    ".article-body p",
                    ".entry-content p",
                    ".post-content p",
                    "section.article-body p",
                ],
                "remove": [
                    ".byline",
                    ".article-date",
                    ".tags",
                    "aside",
                    "nav",
                    ".related-posts",
                ],
            },
        }

    def _pick_domain_key(self, netloc: str) -> str:
        """根据域名选择配置"""
        netloc = netloc.lower()
        for key in self.site_selectors.keys():
            if key in netloc:
                return key
        return netloc

    def _clean_content(self, soup: BeautifulSoup, domain: str) -> None:
        """清理不需要的内容"""
        remove_sel = self.site_selectors.get(domain, {}).get("remove", [])
        general = [
            "script", "style", "nav", "aside", "footer", "header",
            ".ad", ".ads", ".advertisement", ".sponsored",
            ".social", ".share", ".related", ".newsletter", ".subscribe", ".signup",
        ]
        for sel in remove_sel + general:
            try:
                for el in soup.select(sel):
                    el.decompose()
            except Exception:
                continue

    def _is_valid_para(self, text: str) -> bool:
        """检查段落是否有效"""
        if not text:
            return False
        text = text.strip()
        return len(text) >= 20

    def _should_keep_para(self, text: str) -> bool:
        """判断是否保留段落"""
        t = text.strip().lower()
        bad = [
            r"^Advertisement", r"^sponsored", r"^Read more", r"^Share this",
            r"^Follow us", r"^Subscribe", r"^Sign up",
        ]
        for pat in bad:
            if re.search(pat, t):
                return False
        return len(text) >= 30 and len(text.split()) >= 5

    def _clean_para(self, text: str) -> str:
        """清理段落文本"""
        return re.sub(r"\s+", " ", text).strip()

    def _extract_title(self, soup: BeautifulSoup, domain: str) -> str:
        """提取文章标题"""
        selectors = self.site_selectors.get(domain, {}).get("title", ["h1"])
        for sel in selectors:
            try:
                for el in soup.select(sel):
                    title = el.get_text(strip=True)
                    if 10 <= len(title) <= 200:
                        return title
            except Exception:
                continue

        # 备选方案
        mt = soup.find("meta", property="og:title")
        if mt and mt.get("content"):
            return str(mt["content"]).strip()

        tt = soup.find("title")
        if tt:
            title = tt.get_text(strip=True)
            for sep in [" - ", " | ", " :: ", " — "]:
                if sep in title:
                    title = title.split(sep)[0]
                    break
            return title
        return "未找到标题"

    def _extract_content(self, soup: BeautifulSoup, domain: str) -> str:
        """提取文章内容"""
        self._clean_content(soup, domain)
        selectors = self.site_selectors.get(domain, {}).get("content", ["p"])
        paras = []

        for sel in selectors:
            try:
                nodes = soup.select(sel)
                if nodes:
                    for n in nodes:
                        t = n.get_text(strip=True)
                        if self._is_valid_para(t):
                            paras.append(t)
                    if paras:
                        break
            except Exception:
                continue

        # 通用提取
        if not paras:
            containers = ["article", "main", ".content", ".article-body", ".post-content",
                         ".entry-content", "#content"]
            for sel in containers:
                try:
                    c = soup.select_one(sel)
                    if c:
                        for p in c.find_all("p"):
                            t = p.get_text(strip=True)
                            if self._is_valid_para(t):
                                paras.append(t)
                        if paras:
                            break
                except Exception:
                    continue

            if not paras:
                for p in soup.find_all("p"):
                    t = p.get_text(strip=True)
                    if self._is_valid_para(t):
                        paras.append(t)

        # 清理和过滤
        cleaned = []
        for p in paras:
            if self._should_keep_para(p):
                c = self._clean_para(p)
                if c:
                    cleaned.append(c)

        return "\n\n".join(cleaned)

    def extract_article(self, html: str, url: str) -> Tuple[str, str]:
        """从HTML提取文章标题和内容"""
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return "解析失败", ""

        domain_key = self._pick_domain_key(urlparse(url).netloc)
        title = self._extract_title(soup, domain_key)
        content = self._extract_content(soup, domain_key)
        return title, content


class NewsAPIService:
    """新闻API服务类，负责从API获取新闻URL"""
    def __init__(self, cfg: ScrapeConfig, http_client: HttpClient, logger: logging.Logger):
        self.cfg = cfg
        self.http_client = http_client
        self.logger = logger

    def fetch_news_urls(self) -> List[str]:
        """从API获取新闻URL列表"""
        start_time = time.time()
        try:
            ua = random.choice(self.cfg.user_agents)
            headers = {
                "Authorization": f"Bearer {self.cfg.api_token}",
                "Content-Type": "application/json",
                "User-Agent": ua,
            }

            request_data = {}
            data = self.http_client.post(self.cfg.api_url, request_data, headers, self.cfg.request_timeout)
            response_time = time.time() - start_time

            if not data:
                raise APIError("API 返回无效响应")

            if isinstance(data, dict) and "urls" in data:
                urls = data["urls"]
            elif isinstance(data, list):
                urls = data
            else:
                raise APIError("API 返回结构不包含 urls")

            urls = [u for u in urls if isinstance(u, str) and u.startswith("http")]

            # 记录API调用的详细结果
            log_api_call(
                "scraper", "scraping", "NewsAPI",
                self.cfg.api_url, request_data, data,
                response_time, 200
            )

            unified_print(f"API 返回 {len(urls)} 个 URL", "scraper", "scraping")
            return urls

        except NewsProcessingError:
            raise
        except Exception as e:
            error_response_time = time.time() - start_time
            log_api_call(
                "scraper", "scraping", "NewsAPI",
                self.cfg.api_url, {}, {},
                error_response_time, 500, str(e)
            )
            raise APIError(f"API 请求失败: {e}")


class URLStore:
    """URL存储和管理类，负责已抓取和失败URL的持久化"""
    def __init__(self, cfg: ScrapeConfig, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.logger = logger
        self.scraped_path = os.path.join(".", self.cfg.scraped_urls_file)
        self.failed_path = os.path.join(".", self.cfg.failed_urls_file)


    def load_scraped(self) -> set:
        try:
            if os.path.exists(self.scraped_path):
                with open(self.scraped_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return set(data.get("scraped_urls", []))
        except Exception as e: self.logger.error(f"加载已抓取 URL 失败: {e}")
        return set()


    def save_scraped(self, urls: set) -> None:
        try:
            data = {
                "scraped_urls": sorted(urls),
                "last_updated": datetime.now().isoformat(),
                "total_count": len(urls),
            }
            with open(self.scraped_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e: self.logger.error(f"保存已抓取 URL 失败: {e}")


    def load_failed(self) -> Dict[str, Dict]:
        try:
            if os.path.exists(self.failed_path):
                with open(self.failed_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for url, info in data.items():
                    if "last_failed" in info and isinstance(info["last_failed"], str):
                        try:
                            info["last_failed"] = datetime.fromisoformat(info["last_failed"])
                        except Exception: pass
                return data
        except Exception as e: self.logger.error(f"加载失败 URL 失败: {e}")
        return()


    def save_failed(self, failed: Dict[str, Dict]) -> None:
        try:
            serializable = {}
            for url, info in failed.items():
                info_copy = dict(info)
                if isinstance(info_copy.get("last_failed"), datetime):
                    info_copy["last_failed"] = info_copy["last_failed"].isoformat()
                serializable[url] = info_copy
            with open(self.failed_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存失败 URL 失败: {e}")


class NewsScraper:
    """新闻爬虫主类，协调各个组件完成新闻抓取任务"""
    def __init__(self, cfg: Optional[ScrapeConfig] = None) -> None:
        self.cfg = cfg or ScrapeConfig()
        # 若提供随机种子，保证可复现
        if self.cfg.random_seed is not None:
            random.seed(self.cfg.random_seed)

        self.logger = self._init_logger()
        self.url_store = URLStore(self.cfg, self.logger)
        self.http_client = HttpClient(self.cfg)
        self.content_extractor = ContentExtractor(self.cfg)
        self.api_service = NewsAPIService(self.cfg, self.http_client, self.logger)

        self._ensure_store_files()  # 确保记录文件存在
        self._index = itertools.count(1)


    def _init_logger(self) -> logging.Logger:
        """初始化统一的日志记录器"""
        return get_unified_logger("scraper", "scraping")



    def _ensure_store_files(self) -> None:
        """确保记录文件存在（若缺失则写入空结构），避免因为文件缺失中断。"""""
        try:
            if not os.path.exists(self.url_store.scraped_path):
                self.url_store.save_scraped(set())
            if not os.path.exists(self.url_store.failed_path):
                self.url_store.save_failed({})
        except Exception as e:
            self.logger.error(f"初始化记录文件失败（已忽略）：{e}")

    def _pick_batch_from_pool(self, pool: List[str], k: int) -> List[str]:
        """按照配置从 pool 中挑选 k 个 URL 并从池中移除。支持 fifo / random。"""
        k = max(0, min(k, len(pool)))
        if k == 0:
            return []

        if str(self.cfg.pick_mode).lower() == "random":
            # 随机不放回采样：先抽索引，再按降序删除，保证删除时索引不乱
            idxs = sorted(random.sample(range(len(pool)), k), reverse=True)
            batch: List[str] = []
            for i in idxs:
                batch.append(pool[i])
                del pool[i]
            batch.reverse()  # 保持与抽样顺序一致（非必须）
            return batch
        else:
            # FIFO：从队头依次弹出
            return [pool.pop(0) for _ in range(k)]


    def fetch_news_urls_from_api(self) -> List[str]:
        """从API获取新闻URL"""
        return self.api_service.fetch_news_urls()


    def filter_urls(self, urls: List[str]) -> List[str]:
        scraped = self.url_store.load_scraped()
        failed = self.url_store.load_failed()

        keep: List[str] = []
        skipped_scraped = 0
        skipped_failed = 0

        now = datetime.now()
        for u in urls:
            if u in scraped:
                skipped_scraped += 1
                continue
            if u in failed:
                last_failed = failed[u].get("last_failed")
                if isinstance(last_failed, datetime) and now < last_failed + timedelta(hours=self.cfg.retry_interval_hours):
                    skipped_failed += 1
                    continue
            keep.append(u)

        self.logger.info(
            f"过滤后剩余 {len(keep)} 个可用 URL; 跳过已抓取 {skipped_scraped} 个; 跳过近期失败 {skipped_failed} 个"
        )
        return keep


    def _request_html(self, url: str) -> Optional[str]:
        """请求页面HTML内容"""
        for attempt in range(1, self.cfg.per_url_retries + 2):
            try:
                time.sleep(random.uniform(0.5, 1.4))
                ua = random.choice(self.cfg.user_agents)
                headers = {"User-Agent": ua}
                html = self.http_client.get(url, headers, self.cfg.request_timeout)
                if html:
                    return html
            except Exception as e:
                self.logger.warning(
                    f"[{attempt}/{self.cfg.per_url_retries + 1}] 请求失败 {url}: {e}"
                )
                time.sleep(min(4, 0.6 * (2 ** (attempt - 1))))
        return None



    def scrape_one(self, idx: int, url: str) -> Tuple[Optional[Article], Optional[str]]:
        """抓取单个URL的文章内容"""
        start_time = time.time()
        log_processing_step("scraper", "scraping", f"开始抓取文章 {idx}", {"url": url})

        input_data = {"url": url, "index": idx}
        html = self._request_html(url)
        if not html:
            log_processing_result("scraper", "scraping", f"抓取文章 {idx}", input_data,
                                {"error": "获取HTML失败"}, "error", {"url": url})
            log_error("scraper", "scraping", Exception("获取HTML失败"), f"URL: {url}")
            return None, url

        # 使用内容提取器提取文章
        title, content = self.content_extractor.extract_article(html, url)
        if not title or not content:
            log_processing_result("scraper", "scraping", f"抓取文章 {idx}", input_data,
                                {"error": "内容提取失败", "title": title, "content_length": len(content or "")},
                                "error", {"url": url})
            log_error("scraper", "scraping", Exception("内容提取失败"), f"标题或内容为空: {url}")
            return None, url

        # 计算词数
        word_count = count_english_words(content)
        processing_time = time.time() - start_time

        art = Article(
            index=idx,
            url=url,
            title=title,
            content=content,
            content_length=len(content),
            word_count=word_count,
            scraped_at=datetime.now().isoformat()
        )

        output_data = {
            "title": title,
            "content_length": len(content),
            "word_count": word_count,
            "scraped_at": art.scraped_at
        }

        # 记录详细的文章处理结果
        log_article_processing(
            "scraper", "scraping", str(idx), title, url,
            "", content, 0, word_count, processing_time, "success"
        )

        log_processing_result("scraper", "scraping", f"抓取文章 {idx}", input_data,
                            output_data, "success", {"processing_time": processing_time})

        log_processing_step("scraper", "scraping", f"完成文章 {idx}",
                           {"title": title[:50], "word_count": art.word_count, "content_length": art.content_length})
        return art, None


    def run(self) -> ScrapeResults:
        # 记录任务开始
        log_task_start("scraper", "scraping", {
            "max_urls": self.cfg.max_urls,
            "concurrency": self.cfg.concurrency,
            "target_success": max(1, self.cfg.max_urls)
        })

        unified_print("开始新闻爬取任务...", "scraper", "scraping")

        target_success = max(1, self.cfg.max_urls)
        results = ScrapeResults(total=0, success=0, failed=0)

        rounds = 0
        processed: set = set()
        pool: List[str] = []
        starved_relaxed = False

        def refill_pool(relax_failed_skip: bool = False) -> None:
            new_urls = self.fetch_news_urls_from_api()
            if not new_urls: return
            scraped = self.url_store.load_scraped()
            failed_map = self.url_store.load_failed()

            now = datetime.now()
            kept = []
            for u in new_urls:
                if not isinstance(u, str) or not u.startswith("http"): continue
                if u in scraped: continue
                if u in failed_map and relax_failed_skip:
                    last_failed = failed_map[u].get("last_failed")
                    if isinstance(last_failed, datetime):
                        if now < last_failed + timedelta(hours=self.cfg.retry_interval_hours): continue
                if u not in processed: kept.append(u)

            before = len(pool)
            seen = set(pool)
            for u in kept:
                if u not in seen:
                    pool.append(u)
                    seen.add(u)

            self.logger.info(f"本轮补充候选：+{len(pool) - before}（池总量 {len(pool)}）")

        refill_pool()

        while results.success < target_success:
            while not pool and rounds < self.cfg.max_api_rounds:
                rounds += 1
                refill_pool(relax_failed_skip=starved_relaxed)
                if not pool and self.cfg.strict_success and not starved_relaxed:
                    self.logger.warning("候选不足，放宽近期失败跳过限制后重拉。")
                    starved_relaxed = True
                    refill_pool(relax_failed_skip=True)
                if not pool: time.sleep(1.0)

            if not pool: break

            needed = target_success - results.success
            batch_size = min(len(pool), max(1, min(self.cfg.concurrency, needed)))
            batch = self._pick_batch_from_pool(pool, batch_size)

            self.logger.info(f"本轮计划抓取 {len(batch)} 篇 | 目标成功 {target_success} | 已成功 {results.success}")

            with ThreadPoolExecutor(max_workers=max(1, self.cfg.concurrency)) as ex:
                fut_map = {}

                for u in batch:
                    idx = next(self._index)
                    fut = ex.submit(self.scrape_one, idx, u)
                    fut_map[fut] = (idx, u)

                for fut in as_completed(fut_map):
                    results.total += 0
                    _, u = fut_map[fut]

                    try:
                        art, failed_url = fut.result()
                    except Exception as e:
                        self.logger.error(f"抓取异常 {u}: {e}")
                        art, failed_url = None, u

                    if art:
                        results.articles.append(art)
                        results.success += 1
                        results.successful_urls.append(u)

                        if self.cfg.strict_success and results.success >= target_success:
                            for f in fut_map:
                                if not f.done() and not f.cancelled(): f.cancel()
                            pool.clear()
                            break
                    else:
                        results.failed += 1
                        results.failed_urls.append(failed_url or u)

        results.total = results.success + results.failed

        scraped = self.url_store.load_scraped()
        scraped.update(results.successful_urls)
        self.url_store.save_scraped(scraped)
        print(f"已记录 {len(scraped)} 个已爬取 URL，避免重复抓取。")

        failed = self.url_store.load_failed()
        now = datetime.now()
        for u in results.failed_urls:
            if u in failed:
                failed[u]["count"] = int(failed[u].get("count", 0)) + 1
                failed[u]["last_failed"] = now
            else:
                failed[u] = {"count": 1, "last_failed": now, "reason": "抓取失败"}
        self.url_store.save_failed(failed)
        unified_print(f"已记录 {len(failed)} 个失败 URL，用于优化策略。", "scraper", "scraping")

        # 记录任务结束
        success = results.success >= target_success if self.cfg.strict_success else results.success > 0
        log_task_end("scraper", "scraping", success, {
            "total_attempts": results.total,
            "successful_articles": results.success,
            "failed_articles": results.failed,
            "target_success": target_success,
            "scraped_urls_count": len(scraped),
            "failed_urls_count": len(failed)
        })

        unified_print(f"新闻爬取任务完成: 尝试总数 {results.total} | 成功 {results.success} | 失败 {results.failed}", "scraper", "scraping")

        if self.cfg.strict_success and results.success < target_success:
            unified_print(
                f"警告：目标成功 {target_success} 未达成。已进行多轮 API 拉取与放宽失败限制，但候选资源不足或站点强封。",
                "scraper", "scraping", "warning"
            )
        else:
            unified_print("已达成指定成功数目标。", "scraper", "scraping")

        return results


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="新闻爬虫（纯爬取模式，无AI处理）")
    p.add_argument("--output-dir", default=os.getenv("CRAWLER_OUTPUT_DIR", ""))
    p.add_argument("--api-url", default=os.getenv("CRAWLER_API_URL", None))
    p.add_argument("--api-token", default=os.getenv("CRAWLER_API_TOKEN", None))
    p.add_argument("--max-urls", type=int, default=int(os.getenv("CRAWLER_MAX_URLS", "10")))
    p.add_argument("--concurrency", type=int, default=int(os.getenv("CRAWLER_CONCURRENCY", str(DEFAULT_CONCURRENCY_SCRAPER))))
    p.add_argument("--retry-hours", type=int, default=int(os.getenv("CRAWLER_RETRY_HOURS", "24")))
    p.add_argument("--timeout", type=int, default=int(os.getenv("CRAWLER_TIMEOUT", "30")))
    p.add_argument("--strict-success", action="store_true", default=True)
    p.add_argument("--max-api-rounds", type=int, default=int(os.getenv("CRAWLER_MAX_API_ROUNDS", "5")))
    p.add_argument("--per-url-retries", type=int, default=int(os.getenv("CRAWLER_PER_URL_RETRIES", "2")))
    p.add_argument("--pick-mode", choices=["fifo", "random"], default=os.getenv("CRAWLER_PICK_MODE", "random"),
                   help="URL 取样模式：fifo 或 random（默认 random）")
    p.add_argument("--random-seed", type=int, default=(int(os.getenv("CRAWLER_RANDOM_SEED")) if os.getenv("CRAWLER_RANDOM_SEED") else None),
                   help="随机种子，用于 random 模式下结果可复现")

    return p


def save_scraped_data_to_json(results: ScrapeResults, timestamp: str) -> str:
    """
    将爬取结果保存为JSON文件

    Args:
        results: 爬取结果
        timestamp: 时间戳

    Returns:
        str: 保存的文件路径
    """
    start_time = time.time()

    # 准备JSON数据
    json_data = {
        "metadata": {
            "total_articles": results.total,
            "successful_articles": results.success,
            "failed_articles": results.failed,
            "scraped_at": timestamp,
            "scraper_version": "1.0.0"
        },
        "articles": []
    }

    # 处理每篇文章
    for article in results.articles:
        article_data = {
            "id": article.index,
            "title": article.title,
            "url": article.url,
            "content": article.content,
            "words": article.word_count,  # 单词数，不是字符数
            "content_length": article.content_length,  # 字符数
            "scraped_at": article.scraped_at
        }
        json_data["articles"].append(article_data)

    # 生成文件名
    filename = f"scraped_news_{timestamp}.json"

    # 保存到当前工作目录
    filepath = os.path.join(".", filename)
    try:
        json_string = json.dumps(json_data, ensure_ascii=False, indent=2)
        file_size = len(json_string.encode('utf-8'))

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(json_string)

        operation_time = time.time() - start_time

        # 记录文件操作的详细结果
        log_file_operation(
            "scraper", "data_save", "保存爬取数据",
            filepath, file_size, operation_time, "success",
            {
                "article_count": len(json_data['articles']),
                "format": "json",
                "timestamp": timestamp
            }
        )

        unified_print(f"爬取数据已保存到: {filepath}", "scraper", "data_save")
        unified_print(f"共 {len(json_data['articles'])} 篇文章", "scraper", "data_save")
        return filepath
    except Exception as e:
        operation_time = time.time() - start_time

        log_file_operation(
            "scraper", "data_save", "保存爬取数据",
            filepath, 0, operation_time, "error",
            {"error": str(e), "timestamp": timestamp}
        )

        unified_print(f"保存JSON文件失败: {e}", "scraper", "data_save", "error")
        return ""


def main() -> None:
    """命令行入口函数，解析参数并运行完整流程"""
    ap = build_arg_parser()
    args = ap.parse_args()

    cfg = ScrapeConfig(
        output_dir=args.output_dir,
        api_url=args.api_url or DEFAULT_CRAWLER_API_URL,
        api_token=args.api_token or DEFAULT_CRAWLER_API_TOKEN,
        max_urls=max(1, args.max_urls),
        concurrency=max(1, args.concurrency),
        retry_interval_hours=max(1, args.retry_hours),
        request_timeout=max(5, args.timeout),
        strict_success=bool(args.strict_success),
        max_api_rounds=max(1, args.max_api_rounds),
        per_url_retries=max(0, args.per_url_retries),
        pick_mode=args.pick_mode,
        random_seed=args.random_seed,
    )

    scraper = NewsScraper(cfg)
    results = scraper.run()

    unified_print(f"爬取完成！成功抓取 {len(results.articles)} 篇文章", "scraper", "main")

    # 保存爬取数据为JSON文件
    if results.success > 0:
        timestamp = now_stamp()
        save_scraped_data_to_json(results, timestamp)


if __name__ == "__main__":
    main()