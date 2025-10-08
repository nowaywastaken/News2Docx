# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from index import load_app_config, prepare_logging
from news2docx.infra.logging import unified_print


def test_config_example_ui_structure():
    p = Path("config.example.yml")
    cfg = load_app_config(str(p))
    assert isinstance(cfg, dict)
    assert "ui" in cfg and isinstance(cfg["ui"], dict)
    ui = cfg["ui"]
    assert int(ui["fixed_width"]) == 350
    assert int(ui["fixed_height"]) == 600
    assert bool(ui["high_dpi"]) is True


def test_prepare_logging_console_only(tmp_path):
    log_path = tmp_path / "tmp_log.txt"
    prepare_logging(str(log_path))
    unified_print("hello", "test", "case", level="info")
    # Logging to local files is disabled by design; file should not be created
    assert not log_path.exists()
