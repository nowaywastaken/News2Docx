from __future__ import annotations

import os
from typing import List, Optional

# SiliconFlow OpenAI-compatible base (HTTPS enforced)
SILICON_BASE = "https://api.siliconflow.cn/v1"

# 不再使用白名单与 /v1/models；免费模型列表统一来自定价页抓取


def _api_key() -> str | None:
    # Prefer SILICONFLOW_API_KEY, fallback to OPENAI_API_KEY for compatibility
    return os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")


def free_chat_models(timeout: int = 10) -> List[str]:
    """返回可用的免费聊天模型列表。

    优先使用运行期覆盖列表；否则直接抓取定价页的免费模型。
    不再调用 `/v1/models`，不使用任何白名单。
    失败时回退到一个保守默认值。
    """
    # 运行期覆盖（由引擎在任务开始时注入）
    if _RUNTIME_MODELS_OVERRIDE:
        return list(_RUNTIME_MODELS_OVERRIDE)

    try:
        from news2docx.ai.free_models_scraper import scrape_free_models

        names = scrape_free_models(timeout_ms=timeout * 1000)
        # 过滤 Pro/ 前缀，保留免费条目
        free = [n for n in (names or []) if isinstance(n, str) and not n.startswith("Pro/")]
        if free:
            return free
    except Exception:
        pass

    # 兜底默认
    return ["Qwen/Qwen2-7B-Instruct"]


# Optional per-run override injected by engine before a task starts
_RUNTIME_MODELS_OVERRIDE: Optional[List[str]] = None


def set_runtime_models_override(models: Optional[List[str]]) -> None:
    global _RUNTIME_MODELS_OVERRIDE
    _RUNTIME_MODELS_OVERRIDE = list(models) if models else None


def get_runtime_models_override() -> Optional[List[str]]:
    return list(_RUNTIME_MODELS_OVERRIDE) if _RUNTIME_MODELS_OVERRIDE else None


# 不再提供 affordable_chat_models，统一用免费模型策略


__all__ = [
    "free_chat_models",
    "SILICON_BASE",
    "set_runtime_models_override",
    "get_runtime_models_override",
]
