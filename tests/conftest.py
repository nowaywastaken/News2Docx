# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path


def pytest_sessionstart(session) -> None:
    # Ensure project root is importable for tests
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

