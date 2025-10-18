#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plain config loader (encryption removed).

Responsibilities:
- Load YAML/JSON config from path and return as a dict.
- No field-level encryption/decryption; all values are used as-is.

Notes:
- The previous machine-bound AES-GCM encryption has been removed.
- Callers should not expect any mutation to the source config file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from news2docx.core.config import load_config_file


def secure_load_config(config_path: str) -> Dict[str, Any]:
    """Load config file as plain dict without any mutation.

    - Reads JSON/YAML and returns a dict (or empty dict).
    - No encryption/decryption is performed.
    - The file is never modified by this loader.
    """
    p = Path(config_path)
    cfg = load_config_file(p)
    if not isinstance(cfg, dict):
        return {}
    return cfg


__all__ = [
    "secure_load_config",
]
