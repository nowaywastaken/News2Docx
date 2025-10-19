from __future__ import annotations

from pathlib import Path
from typing import Optional

from news2docx.core.utils import ensure_directory, now_stamp


def runs_base_dir(conf: Optional[dict] = None) -> Path:
    """返回固定的 runs 目录路径。"""
    return Path("runs")


def new_run_dir(base: Optional[Path] = None) -> Path:
    """创建新的运行目录。"""
    base_dir = base or Path("runs")
    return ensure_directory(base_dir / now_stamp())
