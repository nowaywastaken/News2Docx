from __future__ import annotations

import os
from pathlib import Path


def ensure_siliconflow_env(conf: dict) -> None:
    """Propagate SiliconFlow API key from config into env if missing."""
    try:
        key = conf.get("siliconflow_api_key") if isinstance(conf, dict) else None
    except Exception:
        key = None
    if key and not os.getenv("SILICONFLOW_API_KEY"):
        os.environ["SILICONFLOW_API_KEY"] = str(key)


def desktop_outdir() -> Path:
    """Return user's Desktop/英文新闻稿 directory, creating it if needed."""
    home = Path.home()
    desktop = home / "Desktop"
    # Avoid embedding Chinese chars directly in source literals
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"
    outdir = desktop / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir

