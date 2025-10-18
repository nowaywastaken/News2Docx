from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:  # optional dependency
    yaml = None  # type: ignore


def _load_yaml(p: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError(
            "PyYAML 未安装，无法读取 YAML 配置。请 `pip install pyyaml` 或改用 JSON 配置文件。"
        )
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_json(p: Path) -> Dict[str, Any]:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f) or {}


def load_config_file(path: Optional[str | Path]) -> Dict[str, Any]:
    """加载 JSON/YAML 配置文件，返回字典。路径为空或文件不存在则返回空字典。"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    if p.suffix.lower() in (".yml", ".yaml"):
        return _load_yaml(p)
    return _load_json(p)


def load_env() -> Dict[str, Any]:
    """从环境变量读取配置。"""
    env = os.environ
    d: Dict[str, Any] = {
        # OpenAI-Compatible envs only
        "openai_api_key": env.get("OPENAI_API_KEY"),
        "openai_api_base": env.get("OPENAI_API_BASE"),
        "max_urls": _to_int(env.get("CRAWLER_MAX_URLS")),
        "concurrency": _to_int(env.get("CONCURRENCY")),
        "retry_hours": _to_int(env.get("CRAWLER_RETRY_HOURS")),
        "timeout": _to_int(env.get("CRAWLER_TIMEOUT")),
        "strict_success": _to_bool(env.get("CRAWLER_STRICT_SUCCESS")),
        "max_api_rounds": _to_int(env.get("CRAWLER_MAX_API_ROUNDS")),
        "per_url_retries": _to_int(env.get("CRAWLER_PER_URL_RETRIES")),
        "pick_mode": env.get("CRAWLER_PICK_MODE"),
        "random_seed": _to_int(env.get("CRAWLER_RANDOM_SEED")),
        "target_language": env.get("TARGET_LANGUAGE"),
        "export_order": env.get("EXPORT_ORDER"),
        "export_mono": _to_bool(env.get("EXPORT_MONO")),
    }
    return {k: v for k, v in d.items() if v is not None}


def _to_int(v: Optional[str]) -> Optional[int]:
    try:
        return int(v) if v is not None and v != "" else None
    except Exception:
        return None


def _to_bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def merge_config(*sources: Dict[str, Any]) -> Dict[str, Any]:
    """左侧优先，逐个覆盖合并。"""
    out: Dict[str, Any] = {}
    for s in sources:
        for k, v in (s or {}).items():
            if v is not None:
                out[k] = v
    return out
