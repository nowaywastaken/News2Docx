# index.py —— 阿里云函数计算(FC) 事件函数 · GDELT Doc 2.0 抓取过去7天新闻URL
# -*- coding: utf-8 -*-
import json
import os
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlencode

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# ========== 默认配置（可用环境变量覆盖）==========
DEFAULT_SITES: List[str] = []


def _read_sites_from_file(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for ln in lines:
        s = (ln or "").strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def default_sites() -> List[str]:
    p = os.getenv("SITES_FILE")
    if not p:
        return []
    return _read_sites_from_file(Path(p))


def _env_sites_or(default_list: List[str]) -> List[str]:
    """读取站点清单，优先 `Websites` (JSON 数组字符串)，其次 `SITES` (CSV)。"""
    v = os.getenv("Websites")
    if v:
        try:
            data = json.loads(v)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            # 若 JSON 解析失败，回退 CSV 逻辑
            pass
    v2 = os.getenv("SITES")
    if v2:
        return [x.strip() for x in v2.split(",") if x.strip()]
    return list(default_list or [])


DEFAULT_TIMESPAN = "7d"  # 过去7天；也可用 24h/30d 或改为绝对时间（另写startdatetime/enddatetime）
DEFAULT_MAX = 50  # 最多返回50条
DEFAULT_SORT = "datedesc"  # 最新在前
BATCH_SIZE = 5  # 每批最多几个域名，避免关键词过于“常见”导致报错
BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FC-Python312-GDELT/1.0)",
    "Accept": "application/json,text/plain,*/*",
}


# ========== 运行期配置（便于测试与解耦） ==========
@dataclass
class Config:
    """运行参数配置。尽量避免在导入阶段做I/O。"""

    sites: List[str]
    timespan: str = DEFAULT_TIMESPAN
    max_per_call: int = DEFAULT_MAX
    sort: str = DEFAULT_SORT
    batch_size: int = BATCH_SIZE
    base_url: str = BASE
    headers: Dict[str, str] = field(default_factory=lambda: dict(REQUEST_HEADERS))
    timeout: int = 20

    @classmethod
    def from_env(cls) -> "Config":
        """根据环境变量构建配置。若未提供 SITES，则优先读同目录 news_website.txt，其次用内置清单。"""
        # 若未设置 SITES，则在运行期尝试读取本地文件
        sites_default = default_sites() or DEFAULT_SITES
        sites = _env_sites_or(sites_default)
        timespan = os.getenv("TIMESPAN", DEFAULT_TIMESPAN)
        max_per_call = env_int("MAX_PER_CALL", DEFAULT_MAX)
        sort = os.getenv("SORT", DEFAULT_SORT)
        batch_size = env_int("BATCH_SIZE", BATCH_SIZE)
        timeout = env_int("TIMEOUT", 20)
        return cls(
            sites=sites,
            timespan=timespan,
            max_per_call=max_per_call,
            sort=sort,
            batch_size=batch_size,
            base_url=BASE,
            headers=dict(REQUEST_HEADERS),
            timeout=timeout,
        )


# ========== 工具函数 ==========
def env_list(name, default_list):
    v = os.getenv(name)
    if not v:
        return default_list
    return [x.strip() for x in v.split(",") if x.strip()]


def env_int(name, default_int):
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default_int
    except Exception:
        return default_int


def chunk(lst, n):
    it = iter(lst)
    while True:
        block = list(islice(it, n))
        if not block:
            return
        yield block


def build_query_from_sites(sites):
    """
    bs = batch_size or BATCH_SIZE
    fetch = fetch or gdelt_fetch
    extractor = extractor or extract_urls
    用 domainis: 精确匹配域名，避免 'keywords too common' / 非JSON错误页。
    例：(domainis:bbc.com OR domainis:cnn.com ...)
    """
    parts = [f"domainis:{d}" for d in sites if d]
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


class NonJSONResponseError(RuntimeError):
    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(
        (requests.RequestException, NonJSONResponseError, json.JSONDecodeError)
    ),
    reraise=True,
)
def gdelt_fetch(query, *, timespan, maxrecords, sort):
    params = {
        "mode": "ArtList",
        "format": "json",
        "sort": sort,
        "timespan": timespan,
        "query": query,
        "maxrecords": maxrecords,
    }
    url = f"{BASE}?{urlencode(params)}"
    resp = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
    resp.raise_for_status()

    # 严检返回是否为 JSON
    ct = (resp.headers.get("Content-Type") or "").lower()
    if "json" not in ct:
        snippet = resp.text[:500].replace("\n", " ")
        raise NonJSONResponseError(f"Non-JSON response: {ct}; snippet: {snippet}")

    try:
        return resp.json()
    except Exception:
        snippet = resp.text[:500].replace("\n", " ")
        raise NonJSONResponseError(f"JSON parse failed; snippet: {snippet}")


def extract_urls(raw_json, lang="eng"):
    """
    仅提取英文 URL；兼容 language 字段可能出现的多种写法：
    English / en / eng（大小写不敏感）
    """
    arts = (raw_json or {}).get("articles", []) or []
    seen, out = set(), []

    # 允许传入 "eng" / "en" / "english" 任意一种
    want = (lang or "eng").strip().lower()
    # 统一成等价集合，既支持调用方传入，也兼容返回值写法
    english_aliases = {"english", "en", "eng"}
    if want in {"english", "en", "eng"}:
        wanted_set = english_aliases
    else:
        # 如果以后你要筛其它语言，这里就按单一等值匹配
        wanted_set = {want}

    for a in arts:
        lang_val = (a.get("language") or "").strip().lower()
        if lang_val not in wanted_set:
            continue
        u = a.get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def do_job(
    *,
    sites,
    timespan,
    max_per_call,
    sort,
    fetch: Optional[Callable[..., dict]] = None,
    batch_size: Optional[int] = None,
    extractor: Optional[Callable[[dict, str], List[str]]] = None,
):
    """
    分批（每批<=BATCH_SIZE个域名）调用 GDELT，再合并去重。
    """
    bs = batch_size or BATCH_SIZE
    fetch = fetch or gdelt_fetch
    extractor = extractor or extract_urls
    all_urls, seen = [], set()
    for batch in chunk(sites, bs):
        query = build_query_from_sites(batch)
        data = fetch(query=query, timespan=timespan, maxrecords=max_per_call, sort=sort)
        urls = extract_urls(data, lang="eng")  # ✅ 强制只取英文
        for u in urls:
            if u not in seen:
                seen.add(u)
                all_urls.append(u)
    return {"count": len(all_urls), "urls": all_urls}


# ========== 事件函数入口 ==========
def handler(
    event, context, *, cfg: Optional[Config] = None, session: Optional[requests.Session] = None
):
    """
    事件函数签名：handler(event, context)
    在控制台“测试函数”里传 {} 即可。
    也支持以下环境变量（不改代码就能调参）：
      SITES="cnn.com,nytimes.com,bbc.com"
      TIMESPAN="7d"        # 或 "24h" / "30d"
      MAX_PER_CALL="250"
      SORT="datedesc"      # 或 "dateasc"
    """
    cfg = cfg or Config.from_env()

    try:
        result = do_job(
            sites=cfg.sites,
            timespan=cfg.timespan,
            max_per_call=cfg.max_per_call,
            sort=cfg.sort,
        )
        return json.dumps(result, ensure_ascii=False).encode("utf-8")
    except Exception as e:
        # 返回结构化错误，便于在控制台排查
        err = {
            "error": e.__class__.__name__,
            "message": str(e),
            "params": {
                "sites": cfg.sites,
                "timespan": cfg.timespan,
                "max_per_call": cfg.max_per_call,
                "sort": cfg.sort,
            },
            "hint": "若仍失败：先把 TIMESPAN 改为 24h；或调小域名数量；或检查函数是否能出公网（VPC需NAT）。",
        }
        return json.dumps(err, ensure_ascii=False).encode("utf-8")
