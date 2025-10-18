#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News2Docx Rich UI entry.

Rules followed per project instructions:
- Single entry: run by `python index.py` with no CLI args.
- All runtime parameters are read from `config.yml`.
- Rich-based TUI as the only UI; PyQt is removed.
- Every step logs to root `log.txt` and console; old logs are cleared on start.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from news2docx.cli.common import ensure_openai_env
from news2docx.infra.logging import init_logging, unified_print
from news2docx.infra.secure_config import secure_load_config

# ---------------- Configuration & Logging ----------------


def load_app_config(config_path: str) -> Dict[str, Any]:
    """加载配置：不再依赖 config.example.yml，缺失时创建最小默认配置。

    - 不进行加密/解密；不修改已存在的配置文件。
    - 若 config.yml 缺失，则直接创建一个可运行的最小模板（等价于 TUI 首次创建）。
    """
    p = Path(config_path)
    if not p.exists():
        try:
            minimal = (
                "openai_api_base: https://api.siliconflow.cn/v1\n"
                'openai_api_key: ""\n'
                "processing_word_min: 350\n"
                "target_language: Chinese\n"
                "merge_short_paragraph_chars: 80\n"
                "processing_forbidden_prefixes: []\n"
                "processing_forbidden_patterns: []\n"
                "export_split: true\n"
                "export_order: zh-en\n"
                "export_mono: false\n"
                "export_font_zh_name: 宋体\n"
                "export_font_zh_size: 10.5\n"
                "export_font_en_name: Cambria\n"
                "export_font_en_size: 10.5\n"
                "export_title_bold: true\n"
            )
            p.write_text(minimal, encoding="utf-8")
            unified_print(
                "已创建最小配置 config.yml（可在 TUI 中修改）", "ui", "config", level="info"
            )
        except Exception as e:
            unified_print(f"创建最小配置失败：{e}", "ui", "config", level="error")
            raise
    data = secure_load_config(str(p))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid config content")
    # 模型相关配置已由代码自动管理，不再填充兼容字段
    return data


def prepare_logging(log_file: str) -> None:
    """Initialize logging to console and file, clearing old logs."""
    # Clear existing log before start (best-effort)
    try:
        Path(log_file).write_text("", encoding="utf-8")
    except Exception:
        pass

    # Initialize console logging
    os.environ["N2D_LOG_LEVEL"] = os.environ.get("N2D_LOG_LEVEL", "INFO")
    init_logging(force=True)

    # Attach file handler
    try:
        import logging

        root = logging.getLogger("")
        if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
            fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            fmt = logging.Formatter(
                "[%(asctime)s][%(levelname)s][%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
            )
            fh.setFormatter(fmt)
            fh.setLevel(root.level)
            root.addHandler(fh)
    except Exception:
        pass

    # 启动时不再输出“logging initialized”提示，避免控制台噪声与重复显示
    # 如需调试，可手动在此处使用 get_unified_logger("ui", "startup").debug(...)


# ---------------- Orchestration (scrape -> process -> export) ----------------


def run_scrape(conf: Dict[str, Any]) -> str:
    """Run scraping according to configuration and return saved JSON path."""
    from news2docx.core.utils import now_stamp
    from news2docx.scrape.runner import NewsScraper, ScrapeConfig, save_scraped_data_to_json

    ensure_openai_env(conf)

    cfg = ScrapeConfig(
        gdelt_timespan=(conf.get("gdelt_timespan") or "7d"),
        gdelt_max_per_call=int(conf.get("gdelt_max_per_call") or 50),
        gdelt_sort=(conf.get("gdelt_sort") or "datedesc"),
        max_urls=int(conf.get("max_urls") or 10),
        concurrency=int(conf.get("concurrency") or 10),
        timeout=int(conf.get("timeout") or 10),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=(int(conf.get("random_seed")) if conf.get("random_seed") is not None else None),
        db_path=str(conf.get("db_path") or (Path.cwd() / ".n2d_cache" / "crawled.sqlite3")),
        noise_patterns=(
            conf.get("noise_patterns") if isinstance(conf.get("noise_patterns"), list) else None
        ),
        required_word_min=(int(conf.get("processing_word_min")) if conf.get("processing_word_min") is not None else None),
    )
    unified_print("scrape start", "ui", "scrape", level="info")
    ns = NewsScraper(cfg)
    results = ns.run()
    ts = now_stamp()
    path = save_scraped_data_to_json(results, ts)
    unified_print(f"scrape saved {path}", "ui", "scrape", level="info")
    return path


def run_process(conf: Dict[str, Any], scraped_json_path: Optional[str]) -> str:
    """Process articles either from scraped JSON or latest run, return processed.json path."""
    import json

    from news2docx.services.processing import articles_from_json
    from news2docx.services.processing import process_articles as svc_process_articles
    from news2docx.services.runs import new_run_dir, runs_base_dir

    unified_print("process start", "ui", "process", level="info")
    if scraped_json_path is None:
        raise RuntimeError("scraped_json_path is required")

    # Validate API key only (base/model are hard-coded/auto)
    ensure_openai_env(conf)
    if not (
        os.getenv("SILICONFLOW_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or conf.get("openai_api_key")
    ):
        unified_print(
            "缺少 API Key（SILICONFLOW_API_KEY 或 OPENAI_API_KEY 或 config.yml: openai_api_key）",
            "ui",
            "error",
            level="error",
        )
        raise RuntimeError("missing API key")

    payload = json.loads(Path(scraped_json_path).read_text(encoding="utf-8"))
    arts = articles_from_json(payload)
    proc = svc_process_articles(arts, conf)
    base = runs_base_dir(conf)
    # If scraped path already under runs/<id>/scraped.json, reuse same run dir
    p_scraped = Path(scraped_json_path)
    if p_scraped.parts and "runs" in p_scraped.parts:
        try:
            idx = p_scraped.parts.index("runs")
            run_dir = Path(*p_scraped.parts[: idx + 2])
            run_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            run_dir = new_run_dir(base)
    else:
        run_dir = new_run_dir(base)
    out_path = run_dir / "processed.json"
    out_path.write_text(json.dumps(proc, ensure_ascii=False, indent=2), encoding="utf-8")
    unified_print(f"processed saved {out_path}", "ui", "process", level="info")
    return str(out_path)


def run_export(conf: Dict[str, Any], processed_json_path: str) -> str:
    """Export DOCX from processed payload and return target path or directory."""
    from pathlib import Path as P

    from news2docx.core.utils import now_stamp
    from news2docx.services.exporting import export_processed

    unified_print("export start", "ui", "export", level="info")
    ts = now_stamp()
    res = export_processed(
        P(processed_json_path), conf, output=None, split=None, default_filename=f"news_{ts}.docx"
    )
    if res.get("split"):
        out_dir = str(P(res["paths"][0]).parent) if res.get("paths") else ""
        unified_print(f"export per-article -> {out_dir}", "ui", "export", level="info")
        return out_dir
    else:
        unified_print(f"export single -> {res.get('path')}", "ui", "export", level="info")
        return str(res.get("path") or "")


# ---------------- Main ----------------


if __name__ == "__main__":
    try:
        from news2docx.tui.tui import main as tui_main

        prepare_logging("log.txt")
        _ = load_app_config("config.yml")
        tui_main()
    except Exception as e:
        unified_print(f"无法启动 Rich TUI：{e}", "ui", "startup", level="error")
