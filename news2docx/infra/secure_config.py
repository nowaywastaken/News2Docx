#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Secure config loader with field-level encryption at rest.

Responsibilities:
- Load YAML/JSON config from path.
- Decrypt sensitive fields transparently using an OS keyring-held master key.
- Auto-encrypt plaintext sensitive fields in config.yml (only), then persist.

Design notes:
- Uses AES-GCM with 256-bit key (cryptography AESGCM).
- Master key is stored in system keyring under a service name from config.
- Never logs plaintext; only logs metadata.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from news2docx.core.config import load_config_file
from news2docx.infra.logging import unified_print


def _require_bytes(b64: str) -> bytes:
    return base64.urlsafe_b64decode(b64.encode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


def _load_or_create_master_key(service: str) -> bytes:
    """Load master key from system keyring or create a new one.

    The key is stored as base64 under (service, "config_master_key").
    """
    import keyring  # lazy import for testability

    user = "config_master_key"
    existing = keyring.get_password(service, user)
    if existing:
        try:
            return _require_bytes(existing)
        except Exception:
            unified_print("invalid master key encoding; regenerating", "secure", "key", level="warn")
    key = secrets.token_bytes(32)
    keyring.set_password(service, user, _b64(key))
    unified_print("master key created in keyring", "secure", "key", level="info")
    return key


def _aesgcm_encrypt(key: bytes, plaintext: str, aad: bytes) -> str:
    aes = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    blob = nonce + ct  # ct includes tag at tail
    return "encgcm:" + _b64(blob)


def _aesgcm_decrypt(key: bytes, token: str, aad: bytes) -> str:
    if not token.startswith("encgcm:"):
        return token
    data = _require_bytes(token.split(":", 1)[1])
    nonce, ct = data[:12], data[12:]
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, aad)
    return pt.decode("utf-8")


def _collect_sensitive_keys(cfg: Dict[str, Any]) -> List[str]:
    sec = cfg.get("security") if isinstance(cfg, dict) else None
    if not isinstance(sec, dict):
        return ["openai_api_key", "crawler_api_token"]
    keys = sec.get("sensitive_keys")
    if isinstance(keys, list) and keys:
        return [str(k) for k in keys]
    return ["openai_api_key", "crawler_api_token"]


def _service_name(cfg: Dict[str, Any]) -> str:
    sec = cfg.get("security") if isinstance(cfg, dict) else None
    if isinstance(sec, dict) and sec.get("keyring_service"):
        return str(sec["keyring_service"])
    return "News2Docx"


def _encryption_enabled(cfg: Dict[str, Any]) -> bool:
    sec = cfg.get("security") if isinstance(cfg, dict) else None
    if isinstance(sec, dict) and isinstance(sec.get("enable_encryption"), bool):
        return bool(sec["enable_encryption"])
    return True


def secure_load_config(config_path: str) -> Dict[str, Any]:
    """Load config and decrypt sensitive fields when configured.

    Behavior:
    - Returns a dict with plaintext for sensitive keys at runtime.
    - If path is exactly "config.yml" and sensitive plaintext is found while
      encryption is enabled, it will encrypt in-place and persist to the same file.
    """
    p = Path(config_path)
    cfg = load_config_file(p)
    if not isinstance(cfg, dict):
        raise RuntimeError("Invalid config content")

    # Short-circuit if encryption disabled
    if not _encryption_enabled(cfg):
        return cfg

    service = _service_name(cfg)
    sensitive = _collect_sensitive_keys(cfg)

    # Determine actions before touching keyring
    should_persist = p.name == "config.yml"
    need_decrypt = False
    need_encrypt = False
    for key in sensitive:
        val = cfg.get(key)
        if isinstance(val, str) and val:
            if val.startswith("encgcm:"):
                need_decrypt = True
            else:
                if should_persist:
                    need_encrypt = True

    if not (need_decrypt or need_encrypt):
        # Nothing to do; return as-is (e.g., config.example.yml)
        return cfg

    aad = f"{service}:{p.name}".encode("utf-8")
    master = _load_or_create_master_key(service)
    modified = False

    for key in sensitive:
        if key not in cfg:
            continue
        val = cfg.get(key)
        if not isinstance(val, str):
            continue
        if val.startswith("encgcm:"):
            try:
                dec = _aesgcm_decrypt(master, val, aad)
                cfg[key] = dec
            except Exception:
                unified_print(f"failed to decrypt field '{key}'", "secure", "decrypt", level="error")
                raise
        else:
            if should_persist:
                enc = _aesgcm_encrypt(master, val, aad)
                cfg[key] = val  # keep runtime plaintext
                try:
                    import yaml  # type: ignore
                    data = load_config_file(p)
                    if isinstance(data, dict):
                        data[key] = enc
                        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
                        modified = True
                        unified_print(f"encrypted field '{key}' and updated config.yml", "secure", "encrypt", level="info")
                except Exception as e:
                    unified_print(f"failed to persist encryption for '{key}': {e}", "secure", "encrypt", level="warn")

    if modified and os.getenv("N2D_LOG_LEVEL"):
        # no-op; placeholder to hint that config changed, logs already emitted
        pass
    return cfg


__all__ = [
    "secure_load_config",
]
