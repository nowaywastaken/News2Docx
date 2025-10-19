from __future__ import annotations

import os
from pathlib import Path


def ensure_openai_env(conf: dict) -> None:
    """将配置中的 API 密钥设置到环境变量。"""
    if not isinstance(conf, dict):
        return
    key = conf.get("openai_api_key")
    if key and not (os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")):
        os.environ["OPENAI_API_KEY"] = str(key)


def desktop_outdir() -> Path:
    """返回桌面输出目录，不存在则创建。"""
    outdir = Path.home() / "Desktop" / "英文新闻稿"
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir
