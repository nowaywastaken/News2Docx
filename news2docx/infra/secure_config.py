#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Secure config loader with field-level encryption at rest.

Responsibilities:
- Load YAML/JSON config from path.
- Decrypt sensitive fields transparently at runtime.
- Auto-encrypt plaintext sensitive fields in config.yml (only), then persist.

Design notes:
- Single scheme: AES-GCM with a machine-bound derived key (no key file).
- Never logs plaintext; only logs metadata.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from news2docx.core.config import load_config_file
from news2docx.infra.logging import unified_print


def _require_bytes(b64: str) -> bytes:
    return base64.urlsafe_b64decode(b64.encode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


# Legacy DPAPI/encgcm support removed.


def _machine_identifier() -> bytes:
    """Return a machine-stable identifier as bytes.

    Priority:
    - Linux: /etc/machine-id or /var/lib/dbus/machine-id (as text bytes)
    - macOS: IOPlatformUUID from ioreg (as text bytes)
    - Fallback: MAC address from uuid.getnode()
    """
    try:
        if os.path.isfile("/etc/machine-id"):
            return Path("/etc/machine-id").read_text(encoding="utf-8").strip().encode("utf-8")
        if os.path.isfile("/var/lib/dbus/machine-id"):
            return Path("/var/lib/dbus/machine-id").read_text(encoding="utf-8").strip().encode(
                "utf-8"
            )
    except Exception:
        pass

    # macOS IOPlatformUUID
    try:
        if os.uname().sysname.lower() == "darwin":  # type: ignore[attr-defined]
            import subprocess

            out = subprocess.check_output([
                "ioreg",
                "-rd1",
                "-c",
                "IOPlatformExpertDevice",
            ], text=True)
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    # format: "IOPlatformUUID" = "XXXX-XXXX-..."
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        v = parts[1].strip().strip('"')
                        if v:
                            return v.encode("utf-8")
    except Exception:
        pass

    # Last resort: MAC address
    try:
        import uuid

        n = uuid.getnode()
        return n.to_bytes(8, "big", signed=False)
    except Exception:
        # random fallback would break stability; raise to be explicit
        raise RuntimeError("unable to obtain a stable machine identifier")


def _derive_machine_key(aad: bytes) -> bytes:
    """Derive a 32-byte key from machine identifier using HKDF-SHA256.

    salt uses AAD to bind to service+file, and info labels the context.
    """
    mid = _machine_identifier()
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=aad, info=b"News2Docx/mach/v1")
    return hkdf.derive(mid)


# Legacy encgcm helpers removed.


def _mach_encrypt(plaintext: str, aad: bytes) -> str:
    key = _derive_machine_key(aad)
    aes = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return "encmach:" + _b64(nonce + ct)


def _mach_decrypt(token: str, aad: bytes) -> str:
    if not token.startswith("encmach:"):
        return token
    data = _require_bytes(token.split(":", 1)[1])
    nonce, ct = data[:12], data[12:]
    key = _derive_machine_key(aad)
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, aad)
    return pt.decode("utf-8")


def _collect_sensitive_keys(cfg: Dict[str, Any]) -> List[str]:
    sec = cfg.get("security") if isinstance(cfg, dict) else None
    if not isinstance(sec, dict):
        # Default sensitive fields include API keys and endpoints
        return ["openai_api_key", "crawler_api_token", "crawler_api_url"]
    keys = sec.get("sensitive_keys")
    if isinstance(keys, list) and keys:
        return [str(k) for k in keys]
    return ["openai_api_key", "crawler_api_token", "crawler_api_url"]


def _service_name(cfg: Dict[str, Any]) -> str:
    # Service name used in AAD composition
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

    # Determine actions before touching storage
    should_persist = p.name == "config.yml"
    need_encrypt = False
    for key in sensitive:
        val = cfg.get(key)
        if isinstance(val, str) and val and not val.startswith("encmach:"):
            if should_persist:
                need_encrypt = True

    if not need_encrypt and not any(
        isinstance(cfg.get(k), str) and str(cfg.get(k)).startswith("encmach:") for k in sensitive
    ):
        # Nothing to do; return as-is (e.g., config.example.yml)
        return cfg

    aad = f"{service}:{p.name}".encode("utf-8")
    modified = False

    for key in sensitive:
        if key not in cfg:
            continue
        val = cfg.get(key)
        if not isinstance(val, str):
            continue
        if isinstance(val, str) and val.startswith("encmach:"):
            try:
                dec = _mach_decrypt(val, aad)
                cfg[key] = dec
            except Exception:
                unified_print(
                    f"failed to decrypt field '{key}'", "secure", "decrypt", level="error"
                )
                raise
        else:
            if should_persist:
                enc = _mach_encrypt(val, aad)
                cfg[key] = val  # keep runtime plaintext
                try:
                    import yaml  # type: ignore

                    data = load_config_file(p)
                    if isinstance(data, dict):
                        data[key] = enc
                        p.write_text(
                            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                            encoding="utf-8",
                        )
                        modified = True
                        unified_print(
                            f"encrypted field '{key}' and updated config.yml",
                            "secure",
                            "encrypt",
                            level="info",
                        )
                except Exception as e:
                    unified_print(
                        f"failed to persist encryption for '{key}': {e}",
                        "secure",
                        "encrypt",
                        level="warn",
                    )

    if modified and os.getenv("N2D_LOG_LEVEL"):
        # no-op; placeholder to hint that config changed, logs already emitted
        pass
    return cfg


__all__ = [
    "secure_load_config",
]
