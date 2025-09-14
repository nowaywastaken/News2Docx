# index.py —— 阿里云函数计算(FC) 事件函数 · GDELT Doc 2.0 抓取过去7天新闻URL
# -*- coding: utf-8 -*-
import os
import json
from urllib.parse import urlencode
from itertools import islice
from pathlib import Path
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ========== 默认配置（可用环境变量覆盖）==========
EMBEDDED_SITES = [
    "apnews.com",
    "afp.com",
    "washingtonpost.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "aljazeera.com",
    "news.sky.com",
    "theguardian.com",
    "thetimes.co.uk",
    "telegraph.co.uk",
    "independent.co.uk",
    "itv.com/news",
    "channel4.com/news",
    "euronews.com",
    "politico.com",
    "axios.com",
    "theatlantic.com",
    "usatoday.com",
    "latimes.com",
    "npr.org",
    "pbs.org/newshour",
    "abcnews.go.com",
    "cbsnews.com",
    "nbcnews.com",
    "cnbc.com",
    "marketwatch.com",
    "forbes.com",
    "fortune.com",
    "theglobeandmail.com",
    "cbc.ca",
    "ctvnews.ca",
    "nationalpost.com",
    "bbc.com", "bbc.co.uk",
    "cnn.com",
    "nytimes.com",
    "who.int",
    "technologyreview.com",
    "wired.com",
    "theverge.com",
    "time.com",
]
DEFAULT_SITES_FILE = Path(__file__).with_name("news_website.txt")

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

def default_sites():
    p = os.getenv("SITES_FILE")
    path = Path(p) if p else DEFAULT_SITES_FILE
    s = _read_sites_from_file(path)
    return s

# Load default sites from file if available; fallback to embedded list
DEFAULT_SITES = default_sites() or EMBEDDED_SITES
DEFAULT_TIMESPAN = "7d"        # 过去7天；也可用 24h/30d 或改为绝对时间（另写startdatetime/enddatetime）
DEFAULT_MAX = 50               # 最多返回50条
DEFAULT_SORT = "datedesc"      # 最新在前
BATCH_SIZE = 5                 # 每批最多几个域名，避免关键词过于“常见”导致报错
BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FC-Python312-GDELT/1.0)",
    "Accept": "application/json,text/plain,*/*",
}

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
    retry=retry_if_exception_type((requests.RequestException, NonJSONResponseError, json.JSONDecodeError)),
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


def do_job(*, sites, timespan, max_per_call, sort):
    """
    分批（每批<=BATCH_SIZE个域名）调用 GDELT，再合并去重。
    """
    all_urls, seen = [], set()
    for batch in chunk(sites, BATCH_SIZE):
        query = build_query_from_sites(batch)
        data = gdelt_fetch(query=query, timespan=timespan, maxrecords=max_per_call, sort=sort)
        urls = extract_urls(data, lang="eng")  # ✅ 强制只取英文
        for u in urls:
            if u not in seen:
                seen.add(u)
                all_urls.append(u)
    return {"count": len(all_urls), "urls": all_urls}

# ========== 事件函数入口 ==========
def handler(event, context):
    """
    事件函数签名：handler(event, context)
    在控制台“测试函数”里传 {} 即可。
    也支持以下环境变量（不改代码就能调参）：
      SITES="cnn.com,nytimes.com,bbc.com"
      TIMESPAN="7d"        # 或 "24h" / "30d"
      MAX_PER_CALL="250"
      SORT="datedesc"      # 或 "dateasc"
    """
    sites = env_list("SITES", DEFAULT_SITES)
    timespan = os.getenv("TIMESPAN", DEFAULT_TIMESPAN)
    max_per_call = env_int("MAX_PER_CALL", DEFAULT_MAX)
    sort = os.getenv("SORT", DEFAULT_SORT)

    try:
        result = do_job(sites=sites, timespan=timespan, max_per_call=max_per_call, sort=sort)
        return json.dumps(result, ensure_ascii=False).encode("utf-8")
    except Exception as e:
        # 返回结构化错误，便于在控制台排查
        err = {
            "error": e.__class__.__name__,
            "message": str(e),
            "params": {
                "sites": sites,
                "timespan": timespan,
                "max_per_call": max_per_call,
                "sort": sort,
            },
            "hint": "若仍失败：先把 TIMESPAN 改为 24h；或调小域名数量；或检查函数是否能出公网（VPC需NAT）。"
        }
        return json.dumps(err, ensure_ascii=False).encode("utf-8")
