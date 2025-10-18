from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from news2docx.core.utils import now_stamp
from news2docx.ai.selector import (
    free_chat_models,
    set_runtime_models_override,
)
from news2docx.infra.logging import (
    log_error,
    log_processing_result,
    log_processing_step,
    log_task_end,
    log_task_start,
)


# OpenAI-Compatible configuration: support split general/translation models
def _load_models_and_base_from_config() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Load translation/general models and api base from root config.yml.

    Returns (model_translation, model_general, api_base). Each item can be None
    if not present. Fallback to legacy `openai_model` for both when split keys
    are absent. This preserves backward compatibility while enabling separation.
    """
    try:
        from pathlib import Path

        import yaml  # type: ignore

        p = Path.cwd() / "config.yml"
        if not p.exists():
            return None, None, None
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return None, None, None
        legacy = data.get("openai_model")
        m_t = data.get("openai_model_translation") or legacy
        m_g = data.get("openai_model_general") or legacy
        base = data.get("openai_api_base")
        return m_t, m_g, base
    except Exception:
        return None, None, None


def _get_translation_model_from_config() -> Optional[str]:
    m_t, _m_g, _b = _load_models_and_base_from_config()
    return m_t


def _get_general_model_from_config() -> Optional[str]:
    _m_t, m_g, _b = _load_models_and_base_from_config()
    return m_g


TARGET_WORD_MIN = 400
# 放弃上限：仅保留下限，内部如需“max”一律视为极大值
TARGET_WORD_MAX = 10**9
DEFAULT_CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))

_CACHE_DIR = os.getenv("N2D_CACHE_DIR", ".n2d_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
_AI_MIN_INTERVAL_MS = int(os.getenv("OPENAI_MIN_INTERVAL_MS", "0") or 0)
_LAST_CALL_MS = 0


@dataclass
class Article:
    index: int
    url: str
    title: str
    content: str
    content_length: int = 0
    word_count: int = 0
    scraped_at: str = field(default_factory=now_stamp)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def estimate_max_tokens(_: int = 1) -> int:
    return min(int(os.getenv("MAX_TOKENS_HARD_CAP", "1200")), 1200)


def _maybe_load_template(path_env: str, default_text: str) -> str:
    p = os.getenv(path_env)
    if not p:
        return default_text
    try:
        return open(p, "r", encoding="utf-8").read()
    except Exception:
        return default_text


TRANSLATION_SYSTEM_PROMPT = """You are a professional {{to}} translator.
STRICT RULES:
- Output ONLY the clean body text, nothing else.
- DO NOT output notes, remarks, timestamps, media names, sources, authors, copyright, image captions, ads, disclaimers, or titles.
- Keep EXACT paragraph count as input; use %% as separator for multi-paragraph input.
"""
TRANSLATION_USER_PROMPT = (
    "Translate to {{to}}. Output clean body only. Do not add any notes or metadata.\n\n{{text}}"
)


def build_translation_prompts(text: str, target_lang: str = "Chinese") -> Tuple[str, str]:
    sys_tpl = _maybe_load_template("TRANSLATION_SYSTEM_PROMPT_FILE", TRANSLATION_SYSTEM_PROMPT)
    usr_tpl = _maybe_load_template("TRANSLATION_USER_PROMPT_FILE", TRANSLATION_USER_PROMPT)
    system_prompt = sys_tpl.replace("{{to}}", target_lang)
    user_prompt = usr_tpl.replace("{{to}}", target_lang).replace("{{text}}", text)
    return system_prompt, user_prompt


def _load_cleaning_config() -> Dict[str, Any]:
    from pathlib import Path

    try:
        import yaml  # type: ignore

        p = Path.cwd() / "config.yml"
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Any] = {}
        out["prefixes"] = list(data.get("processing_forbidden_prefixes") or [])
        out["patterns"] = list(data.get("processing_forbidden_patterns") or [])
        # min_words 与 processing_word_min 对齐
        try:
            mn, _mx = _load_word_bounds()
            out["min_words"] = int(mn)
        except Exception:
            out["min_words"] = 200
        return out
    except Exception:
        # 环境兜底获取 min_words
        try:
            mn, _mx = _load_word_bounds()
            return {"prefixes": [], "patterns": [], "min_words": int(mn)}
        except Exception:
            return {"prefixes": [], "patterns": [], "min_words": 200}


def _load_word_bounds() -> Tuple[int, int]:
    """加载英文原文最小字数（已放弃上限）。

    优先级：
    - config.yml: processing_word_min（忽略 processing_word_max）
    - 环境变量：N2D_WORD_MIN（忽略 N2D_WORD_MAX）
    - 默认常量：TARGET_WORD_MIN
    返回 (min, very_large_max) 以兼容旧签名。
    """
    try:
        from pathlib import Path
        import yaml  # type: ignore

        p = Path.cwd() / "config.yml"
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
        if isinstance(data, dict):
            mn = data.get("processing_word_min")
            if isinstance(mn, int) and mn >= 1:
                return mn, TARGET_WORD_MAX
    except Exception:
        pass
    try:
        mn_s = os.getenv("N2D_WORD_MIN")
        if mn_s:
            mn = int(mn_s)
            if mn >= 1:
                return mn, TARGET_WORD_MAX
    except Exception:
        pass
    return TARGET_WORD_MIN, TARGET_WORD_MAX


def _sanitize_meta(
    text: str, prefixes: List[str], patterns: List[str]
) -> Tuple[str, int, List[str]]:
    """Remove metadata lines and patterns from text; returns (clean_text, removed_count, removed_kinds)."""
    removed = 0
    kinds: List[str] = []
    if not text:
        return "", 0, []
    lines = [ln for ln in (text.splitlines())]
    out_lines: List[str] = []
    # Prefix-based removal
    lower_prefixes = [str(p).strip() for p in (prefixes or []) if str(p).strip()]
    for ln in lines:
        s = ln.strip()
        hit = False
        for pref in lower_prefixes:
            try:
                if s.startswith(pref):
                    removed += 1
                    kinds.append(f"prefix:{pref}")
                    hit = True
                    break
            except Exception:
                continue
        if not hit:
            out_lines.append(ln)
    # Pattern-based removal
    if patterns:
        import re

        tmp_lines: List[str] = []
        for ln in out_lines:
            s = ln.strip()
            matched = False
            for pat in patterns:
                try:
                    if re.match(pat, s):
                        removed += 1
                        kinds.append(f"pattern:{pat}")
                        matched = True
                        break
                except Exception:
                    continue
            if not matched:
                tmp_lines.append(ln)
        out_lines = tmp_lines
    cleaned = "\n".join([line for line in out_lines]).strip()
    return cleaned, removed, kinds


def _cache_get(key: str) -> Optional[str]:
    p = os.path.join(_CACHE_DIR, f"{key}.json")
    if not os.path.exists(p):
        return None
    try:
        data = json.load(open(p, "r", encoding="utf-8"))
        return data.get("content")
    except Exception:
        return None


def _cache_set(key: str, content: str) -> None:
    try:
        json.dump(
            {"content": content},
            open(os.path.join(_CACHE_DIR, f"{key}.json"), "w", encoding="utf-8"),
            ensure_ascii=False,
        )
    except Exception:
        pass


def call_ai_api(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    url: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> str:
    # Auto-select SiliconFlow free chat models with concurrency when model is None.
    api_key = api_key or os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("SILICONFLOW_API_KEY (或 OPENAI_API_KEY) 缺失")
    if max_tokens is None:
        max_tokens = estimate_max_tokens(1)

    # Cache: when model is None, use 'auto' tag to increase hit rate
    key_src = json.dumps(
        {"m": model or "auto", "u": user_prompt, "s": system_prompt, "t": max_tokens},
        ensure_ascii=False,
    ).encode("utf-8")
    cache_key = hashlib.sha256(key_src).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Respect minimal interval between calls (best-effort)
    global _LAST_CALL_MS
    if _AI_MIN_INTERVAL_MS > 0:
        now_ms = int(time.time() * 1000)
        wait = _AI_MIN_INTERVAL_MS - max(0, now_ms - _LAST_CALL_MS)
        if wait > 0:
            time.sleep(wait / 1000.0)

    if model is None:
        from news2docx.ai.chat import chat_first
        # 允许通过环境变量调整超时（默认20s）
        _timeout = int(os.getenv("N2D_CHAT_TIMEOUT", "20") or 20)
        try:
            content = chat_first(
                system_prompt,
                user_prompt,
                models=None,
                api_key=api_key,
                max_tokens=max_tokens,
                timeout=_timeout,
            )
            _LAST_CALL_MS = int(time.time() * 1000)
            _cache_set(cache_key, content)
            return content
        except Exception:
            # 保护性回退：顺序尝试少量稳定模型（避免整体失败）
            try:
                from news2docx.ai.selector import free_chat_models

                pool = free_chat_models() or ["Qwen/Qwen2-7B-Instruct"]
            except Exception:
                pool = ["Qwen/Qwen2-7B-Instruct"]
            # 最多尝试前2个模型，使用同一HTTPS端点
            for mdl in pool[:2]:
                try:
                    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                    body = {
                        "model": mdl,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": max_tokens,
                    }
                    final_url = ("https://api.siliconflow.cn/v1/chat/completions").strip()
                    r = requests.post(final_url, headers=headers, json=body, timeout=_timeout)
                    if r.status_code == 200:
                        data = r.json()
                        content = data["choices"][0]["message"]["content"]
                        _LAST_CALL_MS = int(time.time() * 1000)
                        _cache_set(cache_key, content)
                        return content
                except Exception:
                    continue
            raise

    # Explicit single-model mode (compat) using SiliconFlow endpoint
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    try:
        final_url = (url or "https://api.siliconflow.cn/v1/chat/completions").strip()
        from urllib.parse import urlparse as _urlparse

        _pu = _urlparse(final_url)
        if _pu.scheme.lower() != "https":
            raise RuntimeError(f"安全策略：OpenAI-Compatible 接口必须为 https，当前为：{final_url}")
        # 外部请求超时：可通过 N2D_CHAT_TIMEOUT 调整（默认20s）
        _timeout = int(os.getenv("N2D_CHAT_TIMEOUT", "20") or 20)
        resp = requests.post(final_url, headers=headers, json=body, timeout=_timeout)
        _LAST_CALL_MS = int(time.time() * 1000)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            _cache_set(cache_key, content)
            return content
        if resp.status_code in (429, 500, 502, 503, 504):
            raise RuntimeError(f"provider error {resp.status_code}")
        msg = f"api error {resp.status_code} | url={final_url}"
        if resp.status_code == 401:
            msg += " | 请检查 API Key 权限"
        elif resp.status_code == 404:
            msg += " | 供应商路径不兼容或模型ID无效"
        elif resp.status_code == 403:
            msg += " | 可能无权访问该模型"
        raise RuntimeError(msg)
    except requests.RequestException as e:
        raise RuntimeError(f"network error: {e}")


def _split_paras(text: str) -> List[str]:
    if not text:
        return []
    if "%%" in text:
        return [p.strip() for p in text.split("%%") if p.strip()]
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if parts:
        return parts
    return [p.strip() for p in re.split(r"(?<=[.!?銆傦紒锛焆)\s+", text) if p.strip()]


def ensure_paragraph_parity(translated: str, source: str) -> str:
    src = _split_paras(source)
    dst = _split_paras(translated)
    if not src or not dst:
        return translated
    if len(dst) == len(src):
        return "%%\n".join(dst)
    if len(dst) > len(src):
        merged = dst[: len(src) - 1] + [" ".join(dst[len(src) - 1 :])]
        return "%%\n".join(merged)
    # dst shorter than src: try to split longer dst segments by sentence to match count
    shortage = len(src) - len(dst)
    idx = len(dst) - 1
    sent_split = re.compile(r"(?<=[銆傦紒锛??])\s+")
    while shortage > 0 and idx >= 0:
        parts = [s for s in sent_split.split(dst[idx]) if s.strip()]
        if len(parts) >= 2:
            dst[idx] = parts[0].strip()
            rest = " ".join(parts[1:]).strip()
            dst.insert(idx + 1, rest)
            shortage -= 1
            # keep idx to try further splits if needed
        else:
            idx -= 1
    return "%%\n".join(dst)


def _clean_title_for_processing(title: str) -> str:
    t = (title or "").strip()
    if " | " in t:
        t = t.split(" | ", 1)[0].strip()
    t = t.rstrip(".?!銆傦紒锛?")
    return t


def _is_probably_news(title: str, text: str) -> bool:
    """轻量级启发式判断是否为新闻内容，不抛出异常。"""
    try:
        wc = _count_words(text)
        if wc < 80:
            return False
        paras = _split_paras(text)
        if len(paras) < 2:
            return False
        tokens = (text[:2000] or "").lower()
        hints = [" said", " reports", " according to", "breaking", " news", " report "]
        score = 0
        score += sum(1 for h in hints if h in tokens)
        if (title or "").strip() and len((title or "").strip()) > 10:
            score += 1
        return score >= 1
    except Exception:
        return True


def _chunk_spans(n_items: int, k: int) -> List[Tuple[int, int]]:
    """Split n_items into k contiguous spans [start, end) as evenly as possible.

    Returns list of (start, end) indices. k is clamped to [1, n_items].
    """
    if n_items <= 0:
        return []
    k = max(1, min(int(k), n_items))
    base = n_items // k
    rem = n_items % k
    spans: List[Tuple[int, int]] = []
    start = 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        end = start + size
        spans.append((start, end))
        start = end
    return spans


def _translate_parallel_by_models(text: str, target_lang: str) -> str:
    """Translate text by splitting paragraphs and assigning chunks to different models in parallel.

    - Paragraphs are split via _split_paras and grouped into K contiguous chunks.
    - K = min(number of free chat models, number of paragraphs).
    - Each chunk is translated by a dedicated model (single-model mode) concurrently.
    - Results are concatenated in original order and paragraph parity is enforced at the end.
    """
    paras = _split_paras(text)
    if not paras:
        return ""
    models = free_chat_models()
    if not models:
        # Fallback to default pipeline
        sys_p, usr_p = build_translation_prompts(text, target_lang)
        return call_ai_api(sys_p, usr_p, model=None)

    spans = _chunk_spans(len(paras), min(len(models), len(paras)))
    if not spans:
        sys_p, usr_p = build_translation_prompts(text, target_lang)
        return call_ai_api(sys_p, usr_p, model=None)

    # Build jobs
    jobs: List[Tuple[int, str, str]] = []  # (idx, model, chunk_text)
    for i, (s, e) in enumerate(spans):
        chunk = "%%\n".join(paras[s:e])
        mdl = models[i]
        jobs.append((i, mdl, chunk))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = []
        for idx, mdl, chunk_text in jobs:
            sys_p, usr_p = build_translation_prompts(chunk_text, target_lang)
            futs.append(
                (idx, ex.submit(call_ai_api, sys_p, usr_p, mdl, None, None, estimate_max_tokens(1)))
            )
        for idx, fut in futs:
            try:
                out = fut.result()
                results[idx] = out
            except Exception:
                # On failure of a chunk, fallback to auto model for that chunk
                try:
                    sys_p, usr_p = build_translation_prompts(jobs[idx][2], target_lang)
                    results[idx] = call_ai_api(sys_p, usr_p, model=None)
                except Exception:
                    results[idx] = ""

    ordered = [results[i] for i in range(len(jobs))]
    combined = "\n\n".join(ordered).strip()
    # Enforce final parity against original English text
    return ensure_paragraph_parity(combined, text)


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _adjust_word_count(
    text: str, min_w: int = TARGET_WORD_MIN, max_attempts: int = 2
) -> Tuple[str, int]:
    # 仅确保达到最小字数，不再收缩到上限
    try:
        cfg_min, _cfg_max = _load_word_bounds()
        min_w = cfg_min
    except Exception:
        pass
    wc = _count_words(text)
    if wc >= min_w:
        cfg = _load_cleaning_config()
        cleaned, _rm, _k = _sanitize_meta(text, cfg.get("prefixes", []), cfg.get("patterns", []))
        return (cleaned or text), _count_words(cleaned or text)
    for attempt in range(max_attempts):
        instruction = (
            f"Ensure the output has at least {min_w} words without adding metadata. "
            f"Keep meaning and style; output clean English body only. "
            f"Split paragraphs clearly; use % to separate if needed."
        )
        sys_p = "You are a professional news editor. Output strictly the clean body only."
        usr_p = instruction + "\n\n" + text
        adjusted = call_ai_api(sys_p, usr_p, model=None, max_tokens=estimate_max_tokens(1))
        cfg = _load_cleaning_config()
        adjusted_clean, _rm, _k = _sanitize_meta(
            adjusted, cfg.get("prefixes", []), cfg.get("patterns", [])
        )
        adjusted = adjusted_clean or adjusted
        wc = _count_words(adjusted)
        if wc >= min_w:
            return adjusted, wc
        text = adjusted
    return text, wc


def _parse_model_list(env_var: str) -> List[str]:
    s = os.getenv(env_var, "")
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _first_passing_result(
    system_prompt: str,
    user_prompt: str,
    models: List[str],
    validator,
    *,
    max_tokens: int,
    timeout: int = 60,
) -> Tuple[str, Optional[str]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not models:
        out = call_ai_api(system_prompt, user_prompt, model=None, max_tokens=max_tokens)
        return out, None
    best: Optional[Tuple[str, str]] = None
    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {
            ex.submit(
                call_ai_api,
                system_prompt,
                user_prompt,
                m,
                None,
                None,
                max_tokens,
            ): m
            for m in models
        }
        for f in as_completed(futs):
            m = futs[f]
            try:
                content = f.result()
                if content and validator(content):
                    return content, m
                if content and best is None:
                    best = (m, content)
            except Exception:
                continue
    return (best[1] if best else ""), (best[0] if best else None)


def _adjust_word_count_roles(text: str) -> Tuple[str, int]:
    min_w, _max_w = TARGET_WORD_MIN, TARGET_WORD_MAX
    instruction = (
        f"Ensure the output has at least {min_w} words without adding metadata. "
        f"Keep meaning and style; output clean English body only. "
        f"Split paragraphs clearly; use % to separate if needed."
    )
    sys_p = "You are a professional news editor. Output strictly the clean body only."
    usr_p = instruction + "\n\n" + (text or "")

    def _valid_editor(o: str) -> bool:
        wc = _count_words(o)
        return wc >= min_w

    models = _parse_model_list("N2D_EDITOR_MODELS") or free_chat_models()
    out, _winner = _first_passing_result(
        sys_p,
        usr_p,
        models,
        _valid_editor,
        max_tokens=estimate_max_tokens(1),
    )
    cfg = _load_cleaning_config()
    cleaned, _rm, _k = _sanitize_meta(out or text, cfg.get("prefixes", []), cfg.get("patterns", []))
    adjusted = cleaned or (out or text)
    return adjusted, _count_words(adjusted)


def _translate_with_roles(text: str, target_lang: str) -> str:
    models = _parse_model_list("N2D_TRANSLATOR_MODELS") or free_chat_models()
    sys_p, usr_p = build_translation_prompts(text, target_lang)
    src_paras = _split_paras(text)

    def _valid_trans(o: str) -> bool:
        return bool(o and _count_words(o) > 0)

    out, _winner = _first_passing_result(
        sys_p,
        usr_p,
        models,
        _valid_trans,
        max_tokens=estimate_max_tokens(1),
    )
    out = out or ""
    out = ensure_paragraph_parity(out, text)
    if len(_split_paras(out)) != len(src_paras):
        out = ensure_paragraph_parity(out, text)
    return out


def _merge_short_paragraphs_text(text: str, max_chars: int = 80) -> str:
    paras = _split_paras(text)
    if not paras:
        return text
    i = 0
    while i < len(paras):
        if len(paras[i]) < max_chars:
            prev_len = len(paras[i - 1]) if i > 0 else 10**9
            next_len = len(paras[i + 1]) if i + 1 < len(paras) else 10**9
            if prev_len == 10**9 and next_len == 10**9:
                break
            if next_len <= prev_len and (i + 1) < len(paras):
                paras[i] = (paras[i] + " " + paras[i + 1]).strip()
                del paras[i + 1]
                # keep i to re-evaluate merged length
            elif i > 0:
                paras[i - 1] = (paras[i - 1] + " " + paras[i]).strip()
                del paras[i]
                i = max(i - 1, 0)
            else:
                i += 1
        else:
            i += 1
    return "%%\n".join(paras)


def _merge_short_paragraphs_words(text: str, max_words: int = 80) -> str:
    paras = _split_paras(text)
    if not paras:
        return text
    i = 0
    while i < len(paras):
        wcount = _count_words(paras[i])
        if wcount < max_words:
            prev_w = _count_words(paras[i - 1]) if i > 0 else 10**9
            next_w = _count_words(paras[i + 1]) if i + 1 < len(paras) else 10**9
            if prev_w == 10**9 and next_w == 10**9:
                break
            if next_w <= prev_w and (i + 1) < len(paras):
                paras[i] = (paras[i] + " " + paras[i + 1]).strip()
                del paras[i + 1]
            elif i > 0:
                paras[i - 1] = (paras[i - 1] + " " + paras[i]).strip()
                del paras[i]
                i = max(i - 1, 0)
            else:
                i += 1
        else:
            i += 1
    return "%%\n".join(paras)


def _translate_title(title: str, target_lang: str) -> str:
    if not title:
        return ""
    system_prompt = (
        f"You are a professional {target_lang} title translator. Output only the translation."
    )
    user_prompt = f"Translate to {target_lang}:\n\n{title}"
    try:
        return call_ai_api(
            system_prompt, user_prompt, model=None, max_tokens=estimate_max_tokens(1)
        )
    except Exception:
        return title


def process_article(
    article: Article, target_lang: str = "Chinese", merge_short_chars: Optional[int] = None
) -> Dict[str, Any]:
    start = time.time()
    log_processing_step("engine", "article", f"processing article {article.index}")
    # 仅保留免费通道
    pipeline_mode = "free"
    # Stage 0: word-bound filter for free pipeline OR news check + clean for paid
    if pipeline_mode == "free":
        try:
            bmin, _bmax = _load_word_bounds()
        except Exception:
            bmin, _bmax = TARGET_WORD_MIN, TARGET_WORD_MAX
        wc0 = _count_words(article.content)
        if wc0 < bmin:
            # Early reject without AI editing
            res = {
                "id": str(article.index),
                "original_title": article.title,
                "translated_title": "",
                "original_content": article.content,
                "adjusted_content": article.content,
                "adjusted_word_count": wc0,
                "translated_content": "",
                "target_language": target_lang,
                "processing_timestamp": now_stamp(),
                "url": article.url,
                "success": False,
                "is_news": False,
                "error": "字数低于下限（免费通道）",
            }
            log_processing_result(
                "engine", "article", "skipped", article.to_dict(), res, "wc-filter"
            )
            return res

    # Stage 0b/1: news check + initial cleaning
    log_processing_step("engine", "stage", "news check + clean")
    cfg_clean = _load_cleaning_config()
    clean_title = _clean_title_for_processing(article.title)
    base_clean, rm0, kinds0 = _sanitize_meta(
        article.content, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
    )
    if not base_clean:
        base_clean = article.content
    is_news = _is_probably_news(clean_title, base_clean)
    try:
        log_processing_step("engine", "stage", "news check done")
    except Exception:
        pass
    try:
        log_processing_step("engine", "stage", "clean done")
    except Exception:
        pass
    if (
        os.getenv("N2D_ENFORCE_NEWS", "").strip().lower() in ("1", "true", "yes", "on")
        and not is_news
    ):
        res = {
            "id": str(article.index),
            "original_title": clean_title or article.title,
            "translated_title": "",
            "original_content": article.content,
            "adjusted_content": base_clean,
            "adjusted_word_count": _count_words(base_clean),
            "translated_content": "",
            "target_language": target_lang,
            "processing_timestamp": now_stamp(),
            "url": article.url,
            "success": False,
            "is_news": False,
            "error": "非新闻内容（启用严格检查）",
        }
        log_processing_result("engine", "article", "skipped", article.to_dict(), res, "non-news")
        return res

    roles_mode = os.getenv("N2D_AI_ROLES", "").strip().lower() in ("1", "true", "yes", "roles")

    # Stage 1a: 预合并短段，降低后续AI调用Token（不改变语义）
    try:
        merge_short_chars_eff = int(merge_short_chars or 80)
    except Exception:
        merge_short_chars_eff = 80
    base_clean = _merge_short_paragraphs_words(base_clean, max_words=merge_short_chars_eff)
    if pipeline_mode == "free":
        # No AI editing for word count; use cleaned text as adjusted_raw
        adjusted_raw, final_wc = base_clean, _count_words(base_clean)
    else:
        # Stage 1: word adjust on cleaned content (paid channel)
        if roles_mode:
            adjusted_raw, final_wc = _adjust_word_count_roles(base_clean)
        else:
            adjusted_raw, final_wc = _adjust_word_count(base_clean)
    try:
        log_processing_step("engine", "stage", "adjust done")
    except Exception:
        pass

    # Stage 2: sanitize again after AI editing
    adjusted, rm1, kinds1 = _sanitize_meta(
        adjusted_raw, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
    )
    if not adjusted:
        adjusted = adjusted_raw

    # Stage 3: merge short paragraphs by words (default 80 words)
    adjusted = _merge_short_paragraphs_words(adjusted, max_words=int(merge_short_chars or 80))
    try:
        log_processing_step("engine", "stage", "merge done")
    except Exception:
        pass

    # Enforce minimal word bound once more after cleaning/merging
    try:
        bmin, _bmax = _load_word_bounds()
    except Exception:
        bmin, _bmax = TARGET_WORD_MIN, TARGET_WORD_MAX
    cur_wc = _count_words(adjusted)
    if cur_wc < bmin:
        if os.getenv("N2D_AI_ROLES", "").strip().lower() in ("1", "true", "yes", "roles"):
            adjusted2, _wc2 = _adjust_word_count_roles(adjusted)
        else:
            adjusted2, _wc2 = _adjust_word_count(adjusted, bmin)
        adjusted_clean2, _rmx, _kx = _sanitize_meta(
            adjusted2, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
        )
        adjusted = adjusted_clean2 or adjusted2
    # Stage 4: translation (initial pass)
    # Mark explicit stage: translation begins
    log_processing_step("engine", "stage", "translate start")
    # 默认启用并行翻译（可通过环境变量覆盖）
    _mode = os.getenv("N2D_TRANSLATION_MODE", "parallel").strip().lower()
    if roles_mode:
        translated_raw = _translate_with_roles(adjusted, target_lang)
    elif _mode == "parallel":
        translated_raw = _translate_parallel_by_models(adjusted, target_lang)
    else:
        sys_p, usr_p = build_translation_prompts(adjusted, target_lang)
        translated_raw = call_ai_api(sys_p, usr_p, model=None)
    translated_raw = ensure_paragraph_parity(translated_raw, adjusted)
    translated, rm2, kinds2 = _sanitize_meta(
        translated_raw, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
    )
    if not translated:
        translated = translated_raw
    try:
        log_processing_step("engine", "stage", "translate done")
    except Exception:
        pass
    # Title translation on cleaned title
    translated_title = _translate_title(clean_title or article.title, target_lang)

    # Fallback: if cleaned English falls below min threshold, revert English to adjusted_raw
    # and regenerate translation to keep bilingual parity.
    if _count_words(adjusted) < int(cfg_clean.get("min_words", 200)):
        adjusted = adjusted_raw
        # Regenerate translation against the reverted English text
        if roles_mode:
            translated_raw2 = _translate_with_roles(adjusted, target_lang)
        elif _mode == "parallel":
            translated_raw2 = _translate_parallel_by_models(adjusted, target_lang)
        else:
            sys_p2, usr_p2 = build_translation_prompts(adjusted, target_lang)
            translated_raw2 = call_ai_api(sys_p2, usr_p2, model=None)
        translated_raw2 = ensure_paragraph_parity(translated_raw2, adjusted)
        translated2, rm2b, kinds2b = _sanitize_meta(
            translated_raw2, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
        )
        if not translated2:
            translated2 = translated_raw2
        translated = translated2
        rm2 = rm2b
        kinds2 = kinds2 + kinds2b

    res = {
        "id": str(article.index),
        "original_title": clean_title or article.title,
        "translated_title": translated_title,
        "original_content": article.content,
        "adjusted_content": adjusted,
        # Use the final adjusted text word count to reflect the exported content
        "adjusted_word_count": _count_words(adjusted),
        "translated_content": translated,
        "target_language": target_lang,
        "processing_timestamp": now_stamp(),
        "url": article.url,
        "success": True,
        "is_news": bool(is_news),
        "clean_removed_en": int(rm1),
        "clean_removed_zh": int(rm2),
        "clean_removed_kinds": list(set((kinds0 or []) + kinds1 + kinds2)),
    }
    log_processing_result(
        "engine",
        "article",
        "ok",
        article.to_dict(),
        res,
        "success",
        {"elapsed": time.time() - start},
    )
    return res


def process_articles_two_steps_concurrent(
    articles: List[Article], target_lang: str = "Chinese", merge_short_chars: Optional[int] = None
) -> Dict[str, Any]:
    t0 = time.time()
    log_task_start("engine", "batch", {"count": len(articles), "target_lang": target_lang})
    # 仅保留免费通道
    pipeline_mode = "free"
    # Prefetch models via scraper for this run and inject as per-run override
    try:
        # 仅在本批任务开始时抓取定价页一次，并注入全局覆盖
        from news2docx.ai.free_models_scraper import scrape_free_models

        models = scrape_free_models(timeout_ms=10000)
        if models:
            set_runtime_models_override(models)
            log_processing_step(
                "engine", "models", f"prefetched {len(models)} models via scraper (once)"
            )
            # Rate limits: per model 1000 req/min; 20k-50k tokens/min per model
            # Compute conservative min-interval and concurrency cap
            per_model_rpm = int(os.getenv("N2D_PER_MODEL_RPM", "1000") or 1000)
            per_model_tpm = int(os.getenv("N2D_PER_MODEL_TPM", "20000") or 20000)
            est_tok_per_req = int(os.getenv("N2D_EST_TOKENS_PER_REQ", "1500") or 1500)
            m = max(1, len(models))
            # Minimal global interval so aggregated rate <= m*per_model_rpm
            min_interval_ms = max(1, int(60000 / max(1, m * per_model_rpm)))
            global _AI_MIN_INTERVAL_MS  # type: ignore
            _AI_MIN_INTERVAL_MS = min_interval_ms
            # Concurrency cap by tokens
            max_concurrency_by_tokens = max(1, int((m * per_model_tpm) / max(1, est_tok_per_req)))
        else:
            max_concurrency_by_tokens = DEFAULT_CONCURRENCY
    except Exception:
        # On any failure, clear override to allow default selector to choose
        try:
            set_runtime_models_override(None)
        except Exception:
            pass
        max_concurrency_by_tokens = DEFAULT_CONCURRENCY
    out: List[Dict[str, Any]] = []
    errors = 0
    dyn_workers = max(1, min(DEFAULT_CONCURRENCY, max_concurrency_by_tokens))
    with ThreadPoolExecutor(max_workers=dyn_workers) as ex:
        fut_to_article = {
            ex.submit(process_article, a, target_lang, merge_short_chars): a for a in articles
        }
        for fut in as_completed(fut_to_article):
            a = fut_to_article[fut]
            try:
                out.append(fut.result())
            except Exception as e:
                # Log a clear error for visibility in UI/terminal
                try:
                    log_error(
                        "engine", "article", e, context=f"article {a.index} AI processing failed"
                    )
                except Exception:
                    pass
                errors += 1
                # Fallback: keep original article content so export is not empty
                out.append(
                    {
                        "id": str(a.index),
                        "original_title": a.title,
                        "translated_title": a.title,
                        "original_content": a.content,
                        "adjusted_content": a.content,
                        "translated_content": "",
                        "target_language": target_lang,
                        "processing_timestamp": now_stamp(),
                        "url": a.url,
                        "success": False,
                        "error": str(e),
                    }
                )
    payload = {"articles": out, "metadata": {"processed": len(out), "failed": errors}}
    log_task_end("engine", "batch", errors == 0, {"elapsed": time.time() - t0})
    # Clear per-run override
    try:
        set_runtime_models_override(None)
    except Exception:
        pass
    return payload
