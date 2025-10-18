from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup


class ScraperError(Exception):
    """基础爬虫异常，不向用户暴露底层堆栈。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BusinessError(ScraperError):
    """业务异常，如未找到免费模型。"""


class SystemError(ScraperError):
    """系统异常，如网络失败、渲染失败。"""


@contextmanager
def _playwright() -> Any:  # pragma: no cover - optional runtime path
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover - import error path
        raise SystemError(f"Playwright 加载失败: {exc}")
    try:
        with sync_playwright() as p:  # type: ignore
            yield p
    except Exception as exc:  # pragma: no cover - runtime failure
        raise SystemError(f"Playwright 运行失败: {exc}")


def _fetch_page_html_playwright(url: str, *, timeout_ms: int = 30000) -> str:
    if not url.startswith("https://"):
        raise SystemError("仅允许通过HTTPS抓取页面")
    with _playwright() as p:  # pragma: no cover
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            page.set_extra_http_headers(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                }
            )
            page.goto(url, wait_until="networkidle")
            html = page.content()
            return html
        except Exception as exc:  # pragma: no cover
            raise SystemError(f"页面加载失败: {exc}")
        finally:
            browser.close()


def _fetch_page_html_requests(url: str, *, timeout_s: int = 10) -> str:
    if not url.startswith("https://"):
        raise SystemError("仅允许通过HTTPS抓取页面")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; News2Docx/2.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r = requests.get(url, headers=headers, timeout=timeout_s)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"
        return r.text
    except Exception as exc:
        raise SystemError(f"请求失败: {exc}")


def fetch_page_html(url: str, *, timeout_ms: int = 10000) -> str:
    """获取HTML内容。

    优先在 `N2D_USE_PLAYWRIGHT=1` 时使用无头浏览器；否则用 requests。
    两者均强制 HTTPS。
    """
    use_pw = os.getenv("N2D_USE_PLAYWRIGHT", "").strip().lower() in ("1", "true", "yes", "on")
    if use_pw:
        return _fetch_page_html_playwright(url, timeout_ms=timeout_ms)
    # fallback to requests
    return _fetch_page_html_requests(url, timeout_s=max(1, int(timeout_ms / 1000)))


def parse_free_models(html: str) -> List[str]:
    """从定价页HTML中提取所有“免费”大模型名称。

    收紧规则：
    - 仅在同一模型卡片中出现至少两次“免费”时判定为免费；
    - 排除包含价格符号（¥/￥/$）；
    - 过滤前缀为 `Pro/` 的模型；
    - 名称需匹配 `供应商/模型名` 形式。
    """
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: set[str] = set()

    free_markers = ["免费"]

    def has_free_marker(s: object) -> bool:
        return isinstance(s, str) and any(m in s for m in free_markers)

    name_pattern = re.compile(r"^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.\-]+$")

    for tag in soup.find_all(string=has_free_marker):
        node = getattr(tag, "parent", None)
        card = None
        names_in_node: list[str] = []
        for _ in range(6):
            if not node:
                break
            title_nodes = node.find_all(["h1", "h2", "h3", "h4", "strong", "span", "a"])
            names_in_node = []
            for h in title_nodes:
                txt = (h.get_text(" ", strip=True) or "").strip()
                if txt and name_pattern.match(txt):
                    names_in_node.append(txt)
            if names_in_node:
                card = node
                break
            node = node.parent if getattr(node, "parent", None) else None

        if not card:
            continue
        container_text = card.get_text(" ", strip=True)
        if container_text.count("免费") < 2:
            continue
        if re.search(r"[¥￥$]", container_text):
            continue

        for nm in names_in_node:
            candidates.add(nm)

    probable_classes = [
        "model-name",
        "modelItem-name",
        "price-model-name",
        "card-title",
    ]
    for cls in probable_classes:
        for node in soup.select(f".{cls}"):
            txt = (node.get_text(" ", strip=True) or "").strip()
            if txt:
                candidates.add(txt)

    cleaned: list[str] = []
    for name in candidates:
        name = name.strip()
        if len(name) > 80:
            continue
        if not name_pattern.match(name):
            continue
        if name.startswith("Pro/"):
            continue
        cleaned.append(name)

    cleaned = sorted(set(cleaned))
    if not cleaned:
        raise BusinessError("未能在页面中识别到免费模型")
    return cleaned


def health_check(url: str = "https://siliconflow.cn/pricing", *, timeout: int = 10) -> dict:
    if not url.startswith("https://"):
        raise SystemError("仅允许HTTPS健康检查")
    try:
        # Use requests HEAD to respect project dependency stack
        resp = requests.head(url, timeout=timeout)
        status = int(getattr(resp, "status_code", 0) or 0)
        ok = 200 <= status < 400
        return {"ok": bool(ok), "status": status}
    except Exception as exc:
        raise SystemError(f"健康检查失败: {exc}")


_CACHE_FREE: Dict[str, List[str]] = {}
_CACHE_AFF: Dict[Tuple[str, float], List[str]] = {}


def scrape_free_models(
    url: str = "https://siliconflow.cn/pricing", *, timeout_ms: int = 10000
) -> List[str]:
    # 进程级缓存，避免同一任务内重复抓取
    if url in _CACHE_FREE:
        return list(_CACHE_FREE[url])
    html = fetch_page_html(url, timeout_ms=timeout_ms)
    names = parse_free_models(html)
    _CACHE_FREE[url] = list(names)
    return names


def cmd_scrape(args: argparse.Namespace) -> int:  # pragma: no cover - CLI glue
    try:
        names = scrape_free_models(args.url, timeout_ms=args.timeout_ms)
        print(json.dumps({"free_models": names}, ensure_ascii=False))
        return 0
    except BusinessError as be:
        print(json.dumps({"error": str(be)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except SystemError as se:
        print(json.dumps({"error": str(se)}, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_health(args: argparse.Namespace) -> int:  # pragma: no cover - CLI glue
    try:
        result = health_check(args.url, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except SystemError as se:
        print(json.dumps({"error": str(se)}, ensure_ascii=False), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:  # pragma: no cover - CLI glue
    p = argparse.ArgumentParser(
        prog="siliconflow-pricing-scraper",
        description="抓取 siliconflow.cn/pricing 页面所有免费模型名称",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scrape", help="抓取免费模型")
    ps.add_argument("--url", default="https://siliconflow.cn/pricing", help="目标URL（HTTPS）")
    ps.add_argument("--timeout-ms", type=int, default=30000, help="加载超时(毫秒)")
    ps.set_defaults(func=cmd_scrape)

    ph = sub.add_parser("health", help="健康检查")
    ph.add_argument("--url", default="https://siliconflow.cn/pricing", help="目标URL（HTTPS）")
    ph.add_argument("--timeout", type=int, default=10, help="请求超时(秒)")
    ph.set_defaults(func=cmd_health)

    return p


def main() -> None:  # pragma: no cover - CLI glue
    parser = build_parser()
    args = parser.parse_args()
    code = args.func(args)
    raise SystemExit(code)


__all__ = [
    "ScraperError",
    "BusinessError",
    "SystemError",
    "fetch_page_html",
    "parse_free_models",
    "parse_affordable_models",
    "health_check",
    "scrape_free_models",
    "scrape_affordable_models",
]


def parse_affordable_models(html: str, *, max_price: float = 1.0) -> List[str]:
    """从定价页HTML中提取“输入/输出价格均<=max_price”的模型。

    规则：
    - 在同一模型卡片中找到模型名（供应商/模型名），并解析其中的价格数字（支持¥/￥/$）；
    - 至少找到两处价格（近似视作输入/输出），且均<=max_price；
    - 过滤 Pro/ 前缀模型；
    - 名称匹配 `供应商/模型名`。
    """
    soup = BeautifulSoup(html or "", "html.parser")
    name_pat = re.compile(r"^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.\-]+$")
    price_pat = re.compile(r"[¥￥$]?\s*([0-9]+(?:\.[0-9]+)?)")
    out: set[str] = set()

    def _model_names(node) -> List[str]:
        names: List[str] = []
        for h in node.find_all(["h1", "h2", "h3", "h4", "strong", "span", "a"]):
            t = (h.get_text(" ", strip=True) or "").strip()
            if t and name_pat.match(t):
                names.append(t)
        return names

    for tag in soup.find_all(["div", "section", "article", "li"]):
        text = tag.get_text(" ", strip=True) or ""
        if not text:
            continue
        names = _model_names(tag)
        if not names:
            continue
        prices = [float(m.group(1)) for m in price_pat.finditer(text)]
        if len(prices) < 2:
            continue
        # 取最小的两个价格作为输入/输出的近似（保守）
        prices.sort()
        p_in, p_out = prices[0], prices[1]
        if p_in <= max_price and p_out <= max_price:
            for nm in names:
                if not nm.startswith("Pro/") and name_pat.match(nm):
                    out.add(nm)
    if not out:
        raise BusinessError("未能在页面中识别到符合价格的模型")
    return sorted(out)


def scrape_affordable_models(
    url: str = "https://siliconflow.cn/pricing", *, max_price: float = 1.0, timeout_ms: int = 10000
) -> List[str]:
    key = (url, float(max_price))
    if key in _CACHE_AFF:
        return list(_CACHE_AFF[key])
    html = fetch_page_html(url, timeout_ms=timeout_ms)
    names = parse_affordable_models(html, max_price=max_price)
    _CACHE_AFF[key] = list(names)
    return names
