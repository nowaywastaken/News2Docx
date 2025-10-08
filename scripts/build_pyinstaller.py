#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build News2Docx executable with PyInstaller.

Usage:
  python scripts/build_pyinstaller.py

Notes:
  - Produces `dist/news2docx/` folder (onedir mode) for stability.
  - Excludes `config.yml` by design (may contain secrets). Place your own
    `config.yml` next to the built binary or run from a directory that has it.
  - Includes `assets/` and `config.example.yml` as runtime data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_project_root(expected_marker: str) -> None:
    """Ensure we are in project root by checking the given file exists.

    We avoid clever heuristics and require a clear marker to reduce mistakes.
    """
    marker = Path(expected_marker)
    if not marker.exists():
        print(f"[build] Please run from project root where `{expected_marker}` exists.")
        sys.exit(2)


def add_data_arg(src: str, dst: str) -> str:
    """Format --add-data argument cross-platform.

    Windows uses `SRC;DST`, others use `SRC:DST`.
    """
    sep = ";" if os.name == "nt" else ":"
    return f"{src}{sep}{dst}"


def build_pyinstaller(entry: str, name: str, icon_path: str) -> int:
    """Run PyInstaller with stable, explicit options.

    Returns process exit code (0 for success).
    """
    try:
        from PyInstaller.__main__ import run as pyinstaller_run  # type: ignore
    except Exception as e:
        print("[build] PyInstaller is not installed. Add it to requirements.txt and install.")
        print(f"[build] Error: {e}")
        return 1

    args: list[str] = []
    args.append("--noconfirm")
    args.append("--clean")
    args.append("--onedir")  # prefer stability over single-file extraction
    args.extend(["--name", name])

    # Include assets directory if present
    if Path("assets").exists():
        args.extend(["--add-data", add_data_arg("assets", "assets")])

    # Include example config for user guidance (NOT the real config.yml)
    if Path("config.example.yml").exists():
        args.extend(
            [
                "--add-data",
                add_data_arg("config.example.yml", "config.example.yml"),
            ]
        )

    # Optional icon
    ico = Path(icon_path)
    if ico.exists():
        args.extend(["--icon", str(ico)])

    # Explicit entry
    args.append(entry)

    print("[build] PyInstaller args:")
    for a in args:
        print("  ", a)

    pyinstaller_run(args)
    return 0


def main() -> None:
    ensure_project_root("index.py")
    code = build_pyinstaller(entry="index.py", name="news2docx", icon_path="assets/app.ico")
    if code == 0:
        # Point user to output
        out = Path("dist") / "news2docx"
        print(f"[build] Done. Output: {out}")
    sys.exit(code)


if __name__ == "__main__":
    main()

