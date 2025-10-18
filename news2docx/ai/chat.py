from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from typing import Dict, Iterable, Optional, Tuple

import requests

from news2docx.ai.selector import SILICON_BASE, free_chat_models


def _headers(api_key: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _chat_once(
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str],
    *,
    max_tokens: int,
    timeout: int,
    attempt: int,
) -> Tuple[str, Optional[str]]:
    url = f"{SILICON_BASE}/chat/completions"
    headers = _headers(api_key)
    headers["Content-Type"] = "application/json"
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
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            return model, content
        # 429 在限定重试窗口内可重试（轮次由环境控制，默认4轮）
        _attempts = int(os.getenv("N2D_CHAT_ATTEMPTS", "4") or 4)
        if r.status_code == 429 and attempt < max(0, _attempts - 1):
            # backoff handled by caller (sleep) and retry
            return model, None
        # Map common provider errors to None to allow other models to win
        if r.status_code in (500, 502, 503, 504):
            return model, None
        # Other errors: treat as None (skip)
        return model, None
    except requests.RequestException:
        return model, None


def chat_first(
    system_prompt: str,
    user_prompt: str,
    *,
    models: Optional[Iterable[str]] = None,
    api_key: Optional[str] = None,
    max_tokens: int = 512,
    timeout: int = 10,
) -> str:
    """Send the same message to multiple models concurrently and return the first success.

    - Uses SiliconFlow HTTPS base; no per-run config required.
    - Simple 429 backoff with jitter and up to 5 attempts per model.
    - If all models fail, raises a RuntimeError.
    """
    ms = list(models) if models is not None else free_chat_models()
    if not ms:
        ms = ["Qwen/Qwen2-7B-Instruct"]

    # 轮次由环境变量控制，默认3轮；每轮并发投递到所有模型
    _attempts = int(os.getenv("N2D_CHAT_ATTEMPTS", "4") or 4)
    _attempts = max(1, min(8, _attempts))
    for attempt in range(_attempts):
        # Jittered backoff on attempts > 0 (shared across models)
        if attempt > 0:
            time.sleep(1.2 * attempt + random.random())

        with ThreadPoolExecutor(max_workers=len(ms)) as ex:
            futs = [
                ex.submit(
                    _chat_once,
                    m,
                    system_prompt,
                    user_prompt,
                    api_key,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    attempt=attempt,
                )
                for m in ms
            ]
            for f in as_completed(futs):
                _model, out = f.result()
                if out:
                    return out

    raise RuntimeError("all models failed after retries")


__all__ = ["chat_first"]
