from __future__ import annotations

from typing import Dict, Any, List
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional
    yaml = None  # type: ignore


def load_selector_overrides(path: str | Path) -> Dict[str, Dict[str, List[str]]]:
    p = Path(path)
    if not p.exists():
        return {}
    if p.suffix.lower() in (".yml", ".yaml"):
        if yaml is None:
            return {}
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))

    # normalize structure: ensure keys -> lists of strings
    out: Dict[str, Dict[str, List[str]]] = {}
    for domain, rules in (data or {}).items():
        d: Dict[str, List[str]] = {}
        for k in ("title", "content", "remove"):
            v = rules.get(k) if isinstance(rules, dict) else None
            if isinstance(v, list):
                d[k] = [str(x) for x in v if isinstance(x, (str, bytes))]
        if d:
            out[domain] = d
    return out


def merge_selectors(base: Dict[str, Dict[str, List[str]]], overrides: Dict[str, Dict[str, List[str]]]) -> Dict[str, Dict[str, List[str]]]:
    out = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in base.items()}
    for domain, rules in overrides.items():
        if domain not in out:
            out[domain] = {k: list(v) for k, v in rules.items()}
            continue
        for key in ("title", "content", "remove"):
            if key in rules:
                merged = list(out[domain].get(key, [])) + [x for x in rules[key] if x not in out[domain].get(key, [])]
                out[domain][key] = merged
    return out

