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
from news2docx.infra.logging import (
    log_error,
    log_processing_result,
    log_processing_step,
    log_task_end,
    log_task_start,
)


# OpenAI-Compatible configuration: no hardcoded model name
def _load_model_and_base_from_config() -> Tuple[Optional[str], Optional[str]]:
    """Load `openai_model` and `openai_api_base` from root config.yml if present.

    No defaults here; caller decides fallback/validation strategy.
    """
    try:
        from pathlib import Path

        import yaml  # type: ignore

        p = Path.cwd() / "config.yml"
        if not p.exists():
            return None, None
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return None, None
        return data.get("openai_model"), data.get("openai_api_base")
    except Exception:
        return None, None


TARGET_WORD_MIN = 400
TARGET_WORD_MAX = 450
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
        out["min_words"] = int(data.get("processing_min_words_after_clean") or 200)
        return out
    except Exception:
        return {"prefixes": [], "patterns": [], "min_words": 200}


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
    # OpenAI-Compatible envs only
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    # Resolve model from config if not provided
    if model is None:
        m, _b = _load_model_and_base_from_config()
        model = m
    if not model:
        raise RuntimeError("openai_model is required in config.yml (no backend default)")
    if max_tokens is None:
        max_tokens = estimate_max_tokens(1)

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

    key_src = json.dumps(
        {"m": model, "u": user_prompt, "s": system_prompt, "t": max_tokens}, ensure_ascii=False
    ).encode("utf-8")
    cache_key = hashlib.sha256(key_src).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    global _LAST_CALL_MS
    for attempt in range(3):
        try:
            if _AI_MIN_INTERVAL_MS > 0:
                now_ms = int(time.time() * 1000)
                wait = _AI_MIN_INTERVAL_MS - max(0, now_ms - _LAST_CALL_MS)
                if wait > 0:
                    time.sleep(wait / 1000.0)
            # Resolve final URL: explicit argument > env override > base from config
            base_env = os.getenv("OPENAI_API_BASE")
            base_cfg = _load_model_and_base_from_config()[1]
            base = (base_env or base_cfg or "").strip()
            if not base:
                raise RuntimeError("缺少 OPENAI_API_BASE（或 config.yml: openai_api_base）")
            # Enforce HTTPS for base
            try:
                from urllib.parse import urlparse

                parsed_base = urlparse(base)
                if parsed_base.scheme.lower() != "https":
                    raise RuntimeError(f"安全策略：OPENAI_API_BASE 必须为 https，当前为：{base}")
            except Exception as _e:
                raise RuntimeError(str(_e))
            env_full_url = (os.getenv("OPENAI_API_URL") or "").strip()
            if url:
                final_url = url
            elif env_full_url:
                final_url = env_full_url
            else:
                b = base.rstrip("/")
                # Be tolerant: if base already points to chat endpoint, do not append again
                if b.lower().endswith("/chat/completions"):
                    final_url = b
                else:
                    final_url = b + "/chat/completions"
            # Enforce HTTPS for final URL
            try:
                from urllib.parse import urlparse as _urlparse

                _pu = _urlparse(final_url)
                if _pu.scheme.lower() != "https":
                    raise RuntimeError(
                        f"安全策略：OpenAI-Compatible 接口必须为 https，当前为：{final_url}"
                    )
            except Exception as _e2:
                raise RuntimeError(str(_e2))
            resp = requests.post(final_url, headers=headers, json=body, timeout=120)
            _LAST_CALL_MS = int(time.time() * 1000)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                _cache_set(cache_key, content)
                return content
            elif resp.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise RuntimeError(f"provider error {resp.status_code}")
            else:
                # Provide actionable guidance
                msg = f"api error {resp.status_code} | url={final_url}"
                if resp.status_code == 401:
                    msg += " | 请检查 OPENAI_API_KEY 是否正确/有权限"
                elif resp.status_code == 404:
                    msg += " | 常见原因：openai_api_base 配置为根URL或完整URL不一致；若 base 已含 /chat/completions 则不要重复拼接；也可能是供应商路径不同"
                elif resp.status_code == 403:
                    msg += " | 可能无权访问该模型，请检查模型ID与账号权限"
                raise RuntimeError(msg)
        except requests.RequestException as e:
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise RuntimeError(f"network error: {e}")

    raise RuntimeError("ai call failed")


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


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _adjust_word_count(
    text: str, min_w: int = TARGET_WORD_MIN, max_w: int = TARGET_WORD_MAX, max_attempts: int = 3
) -> Tuple[str, int]:
    wc = _count_words(text)
    if min_w <= wc <= max_w:
        cfg = _load_cleaning_config()
        cleaned, _rm, _k = _sanitize_meta(text, cfg.get("prefixes", []), cfg.get("patterns", []))
        return (cleaned or text), _count_words(cleaned or text)
    for attempt in range(max_attempts):
        target = f"{min_w}-{max_w}"
        instruction = (
            f"Adjust the word count to {target}. Keep style and meaning. "
            f"Output ONLY clean English body text; DO NOT include notes, timestamps, media names, sources, authors, copyright, images, ads, disclaimers, or titles. "
            f"Split paragraphs clearly; use %% to separate if needed."
        )
        sys_p = "You are a professional news editor. Output strictly the clean body only."
        usr_p = instruction + "\n\n" + text
        adjusted = call_ai_api(sys_p, usr_p, max_tokens=estimate_max_tokens(1))
        cfg = _load_cleaning_config()
        adjusted_clean, _rm, _k = _sanitize_meta(
            adjusted, cfg.get("prefixes", []), cfg.get("patterns", [])
        )
        adjusted = adjusted_clean or adjusted
        wc = _count_words(adjusted)
        if min_w <= wc <= max_w:
            return adjusted, wc
        text = adjusted
    return text, wc


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


def _translate_title(title: str, target_lang: str) -> str:
    if not title:
        return ""
    system_prompt = (
        f"You are a professional {target_lang} title translator. Output only the translation."
    )
    user_prompt = f"Translate to {target_lang}:\n\n{title}"
    try:
        return call_ai_api(system_prompt, user_prompt, max_tokens=estimate_max_tokens(1))
    except Exception:
        return title


def process_article(
    article: Article, target_lang: str = "Chinese", merge_short_chars: Optional[int] = None
) -> Dict[str, Any]:
    start = time.time()
    log_processing_step("engine", "article", f"processing article {article.index}")

    # Step 1: word adjust
    adjusted_raw, final_wc = _adjust_word_count(article.content)
    cfg_clean = _load_cleaning_config()
    adjusted, rm1, kinds1 = _sanitize_meta(
        adjusted_raw, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
    )
    if not adjusted:
        adjusted = adjusted_raw
    # Merge short English paragraphs to reduce excessive breaks
    adjusted = _merge_short_paragraphs_text(adjusted, max_chars=int(merge_short_chars or 80))
    # Step 2: translation (initial pass)
    sys_p, usr_p = build_translation_prompts(adjusted, target_lang)
    translated_raw = call_ai_api(sys_p, usr_p)
    translated_raw = ensure_paragraph_parity(translated_raw, adjusted)
    translated, rm2, kinds2 = _sanitize_meta(
        translated_raw, cfg_clean.get("prefixes", []), cfg_clean.get("patterns", [])
    )
    if not translated:
        translated = translated_raw
    # Title translation
    translated_title = _translate_title(article.title, target_lang)

    # Fallback: if cleaned English falls below min threshold, revert English to adjusted_raw
    # and regenerate translation to keep bilingual parity.
    if _count_words(adjusted) < int(cfg_clean.get("min_words", 200)):
        adjusted = adjusted_raw
        # Regenerate translation against the reverted English text
        sys_p2, usr_p2 = build_translation_prompts(adjusted, target_lang)
        translated_raw2 = call_ai_api(sys_p2, usr_p2)
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
        "original_title": article.title,
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
        "clean_removed_en": int(rm1),
        "clean_removed_zh": int(rm2),
        "clean_removed_kinds": list(set(kinds1 + kinds2)),
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
    out: List[Dict[str, Any]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, DEFAULT_CONCURRENCY)) as ex:
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
    return payload
