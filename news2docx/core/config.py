from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


def load_config_file(path: Optional[str | Path]) -> Dict[str, Any]:
    """加载 YAML/JSON 配置文件，返回字典。"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    
    with p.open("r", encoding="utf-8") as f:
        if p.suffix.lower() in (".yml", ".yaml"):
            if yaml is None:
                raise RuntimeError("PyYAML 未安装，请运行: pip install pyyaml")
            return yaml.safe_load(f) or {}
        return json.load(f) or {}
