from __future__ import annotations

import os
from typing import List, Optional

import requests

# SiliconFlow OpenAI-compatible base (HTTPS enforced)
SILICON_BASE = "https://api.siliconflow.cn/v1"

# White-list of known free chat models (can be adjusted)
FREE_IDS = {
    "Qwen/Qwen2-7B-Instruct",
    "Qwen/Qwen2-1.5B-Instruct",
    "Qwen/Qwen1.5-7B-Chat",
    "THUDM/glm-4-9b-chat",
    "THUDM/chatglm3-6b",
    "internlm/internlm2_5-7b-chat",
    "mistralai/Mistral-7B-Instruct-v0.2",
    "01-ai/Yi-1.5-9B-Chat-16K",
    "01-ai/Yi-1.5-6B-Chat",
}


def _api_key() -> str | None:
    # Prefer SILICONFLOW_API_KEY, fallback to OPENAI_API_KEY for compatibility
    return os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")


def free_chat_models(timeout: int = 10) -> List[str]:
    """Fetch available chat-text models and return a filtered free list.

    - Uses HTTPS SiliconFlow `/v1/models` endpoint.
    - Intersects with a curated FREE_IDS whitelist.
    - Excludes any id starting with "Pro/".
    - On error, returns a conservative default list.
    """
    # If engine has prefetched a list for this run, use it
    if _RUNTIME_MODELS_OVERRIDE:
        return list(_RUNTIME_MODELS_OVERRIDE)

    key = _api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = requests.get(
            f"{SILICON_BASE}/models",
            headers=headers,
            params={"type": "text", "sub_type": "chat"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        ids = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
        ids = [i for i in ids if isinstance(i, str) and i]
        free = [mid for mid in ids if mid in FREE_IDS]
        free = [mid for mid in free if not mid.startswith("Pro/")]
        # Final fallback to a sane default if nothing matched
        if free:
            return free
    except Exception:
        # ignore and try scraper fallback below
        pass

    # Optional fallback: scrape pricing page when enabled
    use_scraper = os.getenv("N2D_USE_PRICING_SCRAPER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if use_scraper:
        try:
            from news2docx.ai.free_models_scraper import scrape_free_models

            names = scrape_free_models()
            free = [mid for mid in names if mid in FREE_IDS and not mid.startswith("Pro/")]
            if free:
                return free
        except Exception:
            pass

    # Final default
    return ["Qwen/Qwen2-7B-Instruct"]


# Optional per-run override injected by engine before a task starts
_RUNTIME_MODELS_OVERRIDE: Optional[List[str]] = None


def set_runtime_models_override(models: Optional[List[str]]) -> None:
    global _RUNTIME_MODELS_OVERRIDE
    _RUNTIME_MODELS_OVERRIDE = list(models) if models else None


def get_runtime_models_override() -> Optional[List[str]]:
    return list(_RUNTIME_MODELS_OVERRIDE) if _RUNTIME_MODELS_OVERRIDE else None


def affordable_chat_models(max_price: float = 1.0, timeout: int = 30) -> List[str]:
    """Scrape pricing page for models whose input/output prices are <= max_price.

    Returns a list intersected with FREE_IDS as a conservative allowlist if available;
    otherwise returns the scraped names directly (still filtered for Pro/).
    """
    try:
        from news2docx.ai.free_models_scraper import scrape_affordable_models

        names = scrape_affordable_models(max_price=max_price, timeout_ms=timeout * 1000)
        # Keep non-Pro and optionally intersect with FREE_IDS if you want curated set only
        return [n for n in names if not n.startswith("Pro/")]
    except Exception:
        return free_chat_models(timeout=timeout)


__all__ = [
    "free_chat_models",
    "affordable_chat_models",
    "SILICON_BASE",
    "set_runtime_models_override",
    "get_runtime_models_override",
]
