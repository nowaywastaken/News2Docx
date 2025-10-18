from __future__ import annotations

import os
from pathlib import Path


def ensure_openai_env(conf: dict) -> None:
    """Propagate API key settings from config into env.

    - Prefer `SILICONFLOW_API_KEY`, fallback to `OPENAI_API_KEY`.
    - API base is hard-coded to SiliconFlow; no base injection here.
    """
    if not isinstance(conf, dict):
        return

    # Unified keys
    key = conf.get("openai_api_key")
    if key and not (os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")):
        os.environ["OPENAI_API_KEY"] = str(key)


def desktop_outdir() -> Path:
    """Return user's Desktop/英文新闻稿 directory, creating it if needed."""
    home = Path.home()
    desktop = home / "Desktop"
    # Avoid embedding Chinese chars directly in source literals
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"
    outdir = desktop / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir
