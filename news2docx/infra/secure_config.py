from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from news2docx.core.config import load_config_file


def secure_load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件并返回字典。"""
    cfg = load_config_file(Path(config_path))
    return cfg if isinstance(cfg, dict) else {}
