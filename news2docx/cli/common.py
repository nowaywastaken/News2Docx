from __future__ import annotations

import os
from pathlib import Path


def ensure_openai_env(conf: dict) -> None:
    """Propagate OpenAI-Compatible settings from config into env.

    - Sets OPENAI_API_KEY
    - Sets OPENAI_API_BASE if provided in config
    """
    if not isinstance(conf, dict):
        return

    # Unified keys
    key = conf.get("openai_api_key")
    base = conf.get("openai_api_base")

    if key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = str(key)

    if base and not os.getenv("OPENAI_API_BASE"):
        os.environ["OPENAI_API_BASE"] = str(base)


def desktop_outdir() -> Path:
    """Return user's Desktop/英文新闻稿 directory, creating it if needed."""
    home = Path.home()
    desktop = home / "Desktop"
    # Avoid embedding Chinese chars directly in source literals
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"
    outdir = desktop / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir
