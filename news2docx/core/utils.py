from __future__ import annotations

import os
import re
import time
from typing import Union


def now_stamp() -> str:
    """返回 YYYYMMDD_HHMMSS 时间戳。"""
    return time.strftime("%Y%m%d_%H%M%S")


def safe_filename(filename: str, max_length: int = 255) -> str:
    """清理文件名，移除不安全字符并限制长度。保留扩展名。"""
    if not filename:
        return f"untitled_{now_stamp()}"

    # 拆分扩展名，清理主名
    name, ext = os.path.splitext(filename.strip())
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    ext = re.sub(r"\s+", "", ext)

    if not name:
        name = f"untitled_{now_stamp()}"

    total_len = len(name.encode("utf-8")) + len(ext.encode("utf-8"))
    if total_len > max_length:
        # 简单按字符截断主名，保留扩展名
        # 这里不按字节截断，避免复杂度；一般足够
        keep = max(1, max_length - len(ext))
        name = name[:keep]

    return f"{name}{ext}"

