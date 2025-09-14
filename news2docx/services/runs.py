from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from news2docx.core.utils import ensure_directory


def runs_base_dir(conf: Optional[dict] = None) -> Path:
    base = os.getenv("RUNS_DIR") or (conf.get("runs_dir") if isinstance(conf, dict) else None) or "runs"
    return Path(str(base))


def new_run_dir(base: Optional[Path] = None) -> Path:
    base_dir = base or Path("runs")
    from news2docx.core.utils import now_stamp

    run_id = now_stamp()
    return ensure_directory(base_dir / run_id)


def latest_run_dir(base: Optional[Path] = None) -> Optional[Path]:
    base_dir = base or Path("runs")
    if not base_dir.exists():
        return None
    runs = sorted(base_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


def clean_runs(base: Path, keep: int) -> List[Path]:
    deleted: List[Path] = []
    runs = sorted(base.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in runs[keep:]:
        try:
            for f in p.glob("*"):
                f.unlink(missing_ok=True)
            p.rmdir()
            deleted.append(p)
        except Exception:
            # Ignore individual deletion failures; caller can log
            pass
    return deleted

