from __future__ import annotations

import json
import os
import re
import time
import hashlib
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from news2docx.core.utils import now_stamp
from news2docx.infra.logging import (
    log_task_start, log_task_end, log_processing_step, log_processing_result, log_api_call
)


# OpenAI-Compatible defaults
DEFAULT_MODEL_ID = os.environ.get("OPENAI_MODEL", "THUDM/glm-4-9b-chat")
DEFAULT_OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api..cn/v1")

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
Rules:
- Output only the translation text, no extra words
- Keep exact paragraph count as input; use %% as separator for multi-paragraph input
"""
TRANSLATION_USER_PROMPT = "Translate to {{to}}:\n\n{{text}}"


def build_translation_prompts(text: str, target_lang: str = "Chinese") -> Tuple[str, str]:
    sys_tpl = _maybe_load_template("TRANSLATION_SYSTEM_PROMPT_FILE", TRANSLATION_SYSTEM_PROMPT)
    usr_tpl = _maybe_load_template("TRANSLATION_USER_PROMPT_FILE", TRANSLATION_USER_PROMPT)
    system_prompt = sys_tpl.replace("{{to}}", target_lang)
    user_prompt = usr_tpl.replace("{{to}}", target_lang).replace("{{text}}", text)
    return system_prompt, user_prompt


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
        json.dump({"content": content}, open(os.path.join(_CACHE_DIR, f"{key}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def call_ai_api(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL_ID,
                api_key: Optional[str] = None, url: Optional[str] = None,
                max_tokens: Optional[int] = None) -> str:
    # OpenAI-Compatible envs only
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
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

    key_src = json.dumps({"m": model, "u": user_prompt, "s": system_prompt, "t": max_tokens}, ensure_ascii=False).encode("utf-8")
    cache_key = hashlib.sha256(key_src).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    global _LAST_CALL_MS
    for attempt in range(3):
        t0 = time.time()
        try:
            if _AI_MIN_INTERVAL_MS > 0:
                now_ms = int(time.time() * 1000)
                wait = _AI_MIN_INTERVAL_MS - max(0, now_ms - _LAST_CALL_MS)
                if wait > 0:
                    time.sleep(wait / 1000.0)
            # Resolve final URL: explicit argument > env override > base + chat path
            base = os.getenv("OPENAI_API_BASE") or DEFAULT_OPENAI_API_BASE
            env_full_url = os.getenv("OPENAI_API_URL")
            final_url = url or env_full_url or (base.rstrip("/") + "/chat/completions")
            resp = requests.post(final_url, headers=headers, json=body, timeout=120)
            _LAST_CALL_MS = int(time.time() * 1000)
            total_ms = int((time.time() - t0) * 1000)
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
                raise RuntimeError(f"api error {resp.status_code}")
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


def _adjust_word_count(text: str, min_w: int = TARGET_WORD_MIN, max_w: int = TARGET_WORD_MAX, max_attempts: int = 3) -> Tuple[str, int]:
    wc = _count_words(text)
    if min_w <= wc <= max_w:
        return text, wc
    for attempt in range(max_attempts):
        target = f"{min_w}-{max_w}"
        instruction = (
            f"Adjust the word count to {target}. Keep style and meaning. "
            f"Segment into clear paragraphs."
        )
        sys_p = "You are a professional news editor."
        usr_p = instruction + "\n\n" + text
        adjusted = call_ai_api(sys_p, usr_p, max_tokens=estimate_max_tokens(1))
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
    system_prompt = f"You are a professional {target_lang} title translator. Output only the translation."
    user_prompt = f"Translate to {target_lang}:\n\n{title}"
    try:
        return call_ai_api(system_prompt, user_prompt, max_tokens=estimate_max_tokens(1))
    except Exception:
        return title


def process_article(article: Article, target_lang: str = "Chinese", merge_short_chars: Optional[int] = None) -> Dict[str, Any]:
    start = time.time()
    log_processing_step("engine", "article", f"processing article {article.index}")

    # Step 1: word adjust
    adjusted, final_wc = _adjust_word_count(article.content)
    # Merge short English paragraphs to reduce excessive breaks
    adjusted = _merge_short_paragraphs_text(adjusted, max_chars=int(merge_short_chars or 80))
    # Step 2: translation
    sys_p, usr_p = build_translation_prompts(adjusted, target_lang)
    translated = call_ai_api(sys_p, usr_p)
    translated = ensure_paragraph_parity(translated, adjusted)
    # Title translation
    translated_title = _translate_title(article.title, target_lang)

    res = {
        "id": str(article.index),
        "original_title": article.title,
        "translated_title": translated_title,
        "original_content": article.content,
        "adjusted_content": adjusted,
        "adjusted_word_count": final_wc,
        "translated_content": translated,
        "target_language": target_lang,
        "processing_timestamp": now_stamp(),
        "url": article.url,
        "success": True,
    }
    log_processing_result("engine", "article", "ok", article.to_dict(), res, "success", {"elapsed": time.time() - start})
    return res


def process_articles_two_steps_concurrent(articles: List[Article], target_lang: str = "Chinese", merge_short_chars: Optional[int] = None) -> Dict[str, Any]:
    t0 = time.time()
    log_task_start("engine", "batch", {"count": len(articles), "target_lang": target_lang})
    out: List[Dict[str, Any]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, DEFAULT_CONCURRENCY)) as ex:
        futs = [ex.submit(process_article, a, target_lang, merge_short_chars) for a in articles]
        for fut in as_completed(futs):
            try:
                out.append(fut.result())
            except Exception as e:
                errors += 1
                out.append({"success": False, "error": str(e)})
    payload = {"articles": out, "metadata": {"processed": len(out), "failed": errors}}
    log_task_end("engine", "batch", errors == 0, {"elapsed": time.time() - t0})
    return payload

