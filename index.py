#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""News2Docx PyQt UI entry.

Rules followed per project instructions:
- Single entry: run by `python index.py` with no CLI args.
- All runtime parameters are read from `config.yml`.
- Fixed window size (350x600), High DPI enabled.
- Only Absolute Positioning, QFormLayout, and QStackedLayout are used.
- Every step logs to root `log.txt` and console (single file, no time-splitting).
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from news2docx.cli.common import ensure_openai_env
from news2docx.infra.logging import init_logging, unified_print
from news2docx.infra.secure_config import secure_load_config

# ---------------- Configuration & Logging ----------------


def load_app_config(config_path: str) -> Dict[str, Any]:
    """Load application configuration via secure loader.

    This enforces field-level encryption for sensitive keys when enabled
    by config, while returning plaintext values for runtime use.
    """
    p = Path(config_path)
    if not p.exists():
        # Auto-generate from example when missing
        example_local = p.with_name("config.example.yml")
        example_root = Path.cwd() / "config.example.yml"
        example = example_local if example_local.exists() else example_root
        if example.exists():
            try:
                content = example.read_text(encoding="utf-8")
                p.write_text(content, encoding="utf-8")
                unified_print(
                    f"config.yml not found, created from {example.name}",
                    "ui",
                    "config",
                    level="info",
                )
            except Exception as e:
                unified_print(
                    f"failed to create config.yml from example: {e}",
                    "ui",
                    "config",
                    level="error",
                )
                raise
        else:
            raise FileNotFoundError(
                "config.yml not found and config.example.yml is missing"
            )
    data = secure_load_config(str(p))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid config content")
    return data


def prepare_logging(log_file: str) -> None:
    """Initialize console-only logging (no local file writes)."""
    # Respect level if provided; do not set N2D_LOG_FILE
    os.environ["N2D_LOG_LEVEL"] = os.environ.get("N2D_LOG_LEVEL", "INFO")
    init_logging(force=True)
    unified_print("logging initialized (console only)", "ui", "startup", level="info")


# ---------------- Orchestration (scrape -> process -> export) ----------------


def run_scrape(conf: Dict[str, Any]) -> str:
    """Run scraping according to configuration and return saved JSON path."""
    from news2docx.core.utils import now_stamp
    from news2docx.scrape.runner import (
        DEFAULT_CRAWLER_API_URL,
        save_scraped_data_to_json,
    )
    from news2docx.scrape.runner import (
        NewsScraper as NewsScraper,
    )
    from news2docx.scrape.runner import (
        ScrapeConfig as ScrapeConfig,
    )

    ensure_openai_env(conf)

    mode = str(conf.get("crawler_mode") or "remote").lower()
    token = conf.get("crawler_api_token")
    cfg = ScrapeConfig(
        api_url=conf.get("crawler_api_url") or DEFAULT_CRAWLER_API_URL,
        api_token=token,
        mode=mode,
        sites_file=(
            conf.get("crawler_sites_file") or str(Path.cwd() / "server" / "news_website.txt")
        ),
        gdelt_timespan=(conf.get("gdelt_timespan") or "7d"),
        gdelt_max_per_call=int(conf.get("gdelt_max_per_call") or 50),
        gdelt_sort=(conf.get("gdelt_sort") or "datedesc"),
        max_urls=int(conf.get("max_urls") or 1),
        concurrency=int(conf.get("concurrency") or 4),
        timeout=int(conf.get("timeout") or 30),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=(int(conf.get("random_seed")) if conf.get("random_seed") is not None else None),
        db_path=str(conf.get("db_path") or (Path.cwd() / ".n2d_cache" / "crawled.sqlite3")),
        noise_patterns=(
            conf.get("noise_patterns") if isinstance(conf.get("noise_patterns"), list) else None
        ),
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
    from pathlib import Path

    from news2docx.services.processing import (
        articles_from_json,
    )
    from news2docx.services.processing import (
        process_articles as svc_process_articles,
    )
    from news2docx.services.runs import new_run_dir, runs_base_dir

    unified_print("process start", "ui", "process", level="info")
    if scraped_json_path is None:
        raise RuntimeError("scraped_json_path is required")

    # Validate AI配置（早失败，明确提示）
    # 需要：openai_api_key、openai_api_base（根URL或完整chat URL均可）、openai_model（config.yml）
    ensure_openai_env(conf)
    missing: list[str] = []
    if not (os.getenv("OPENAI_API_KEY") or conf.get("openai_api_key")):
        missing.append("openai_api_key")
    if not (
        os.getenv("OPENAI_API_BASE") or conf.get("openai_api_base") or os.getenv("OPENAI_API_URL")
    ):
        missing.append("openai_api_base")
    if not conf.get("openai_model"):
        missing.append("openai_model")
    if missing:
        unified_print(
            f"AI配置缺失: {', '.join(missing)}；请在 config.yml 中补全（openai_api_base 建议为根URL，如 https://api.siliconflow.cn/v1）",
            "ui",
            "error",
            level="error",
        )
        raise RuntimeError(f"missing AI config: {', '.join(missing)}")

    payload = json.loads(Path(scraped_json_path).read_text(encoding="utf-8"))
    arts = articles_from_json(payload)
    proc = svc_process_articles(arts, conf)
    base = runs_base_dir(conf)
    # If scraped path is already under runs/<id>/scraped.json, reuse the same run dir
    p_scraped = Path(scraped_json_path)
    if p_scraped.parts and "runs" in p_scraped.parts:
        # runs/<id>/scraped.json -> parent is the run dir
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
        # return directory when split
        out_dir = str(P(res["paths"][0]).parent) if res.get("paths") else ""
        unified_print(f"export per-article -> {out_dir}", "ui", "export", level="info")
        return out_dir
    else:
        unified_print(f"export single -> {res.get('path')}", "ui", "export", level="info")
        return str(res.get("path") or "")


# (Doctor self-check removed per requirement)

# ---------------- UI ----------------


class _QtUnavailable(Exception):
    pass


# ---------------- Bootstrap ----------------


def run_app() -> None:
    # Lazy import Qt to avoid hard dependency at import time (for tests)
    try:
        # Ensure Path is available to inner methods via closure to avoid NameError in threads
        from pathlib import Path as Path  # shadow module-level safely for closures

        from PyQt6.QtCore import QCoreApplication, Qt, QTimer
        from PyQt6.QtGui import QGuiApplication, QIcon
        from PyQt6.QtWidgets import (
            QApplication,
            QFormLayout,
            QLabel,
            QPushButton,
            QStackedLayout,
            QTextEdit,
            QWidget,
        )
    except Exception as e:
        raise _QtUnavailable("PyQt6 is required to run the UI. Please install requirements.") from e

    class MainWindow(QWidget):
        """Main window: single action button; navigation and utilities as links.

        - Absolute positioning for header/action/links
        - QStackedLayout for pages
        - QFormLayout for forms
        """

        def __init__(self, config: Dict[str, Any]):
            super().__init__()
            # Ensure Path is available in method scope to avoid NameError in some runtimes
            from pathlib import Path

            self.config = config
            self.setWindowTitle(str(config.get("app", {}).get("name") or "News2Docx UI"))
            icon_path = Path("assets/app.ico")
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
            self.setFixedSize(
                int(config.get("ui", {}).get("fixed_width") or 350),
                int(config.get("ui", {}).get("fixed_height") or 600),
            )

            theme = config.get("ui", {}).get("theme") or {}
            self._primary = str(theme.get("primary_color") or "#4C7DFF")
            self._bg = str(theme.get("background_color") or "#F7F9FC")
            self._text = str(theme.get("text_color") or "#1F2937")
            self.setStyleSheet(f"background-color: {self._bg}; color: {self._text};")

            self.title = QLabel(self.windowTitle(), self)
            self.title.setGeometry(16, 10, 260, 24)
            self.title.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {self._primary};")

            # Nav links (QLabel as link) to reduce buttons
            self.link_home = QLabel("<a href='#home'>主页</a>", self)
            self.link_home.setGeometry(16, 40, 40, 24)
            self.link_home.setOpenExternalLinks(False)
            self.link_settings = QLabel("<a href='#settings'>设置</a>", self)
            self.link_settings.setGeometry(60, 40, 40, 24)
            self.link_settings.setOpenExternalLinks(False)

            # Count input with +/- steppers (absolute positioning)
            self.input_count = QLabel("数量", self)
            # Align top and height with run button (28px height)
            self.input_count.setGeometry(170, 36, 28, 28)
            from PyQt6.QtWidgets import QLineEdit

            # Use three compact widgets within the original 54px slot to avoid layout shifts
            # [-] [display] [+] in 54px width: 18/18/18
            self.btn_count_minus = QPushButton("-", self)
            self.btn_count_minus.setGeometry(200, 36, 18, 28)
            self.btn_count_minus.setStyleSheet("font-weight:600;")

            self.input_count_display = QLineEdit(self)
            self.input_count_display.setGeometry(220, 36, 18, 28)
            self.input_count_display.setText("1")  # default value = 1
            try:
                self.input_count_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
            except Exception:
                pass
            self.input_count_display.setReadOnly(True)

            self.btn_count_plus = QPushButton("+", self)
            self.btn_count_plus.setGeometry(240, 36, 18, 28)
            self.btn_count_plus.setStyleSheet("font-weight:600;")

            # Wire stepper events
            self.btn_count_minus.clicked.connect(lambda: self._adjust_count(-1))
            self.btn_count_plus.clicked.connect(lambda: self._adjust_count(1))

            # Single action button: one-click run
            self.btn_run_all = QPushButton("一键运行", self)
            self.btn_run_all.setGeometry(260, 36, 72, 28)

            self.container = QWidget(self)
            self.container.setGeometry(16, 80, 318, 504)
            self.stack = QStackedLayout()
            self.container.setLayout(self.stack)

            # Prefer worker-driven progress over log-driven mapping
            self._use_log_bridge_progress = False
            self.page_home = self._build_home_page()
            self.page_settings = self._build_settings_page(self.config)
            self.stack.addWidget(self.page_home)
            self.stack.addWidget(self.page_settings)
            self.stack.setCurrentIndex(int(self.config.get("ui", {}).get("initial_page") or 0))

            self.link_home.linkActivated.connect(lambda _: self.stack.setCurrentIndex(0))
            self.link_settings.linkActivated.connect(lambda _: self.stack.setCurrentIndex(1))
            self.btn_run_all.clicked.connect(self._on_run_all)

            # Realtime log bridge + progress
            try:
                self._install_log_bridge()
            except Exception:
                pass

            unified_print("ui ready", "ui", "startup", level="info")

        def _build_home_page(self) -> QWidget:
            from pathlib import Path

            from PyQt6.QtWidgets import QProgressBar, QLineEdit, QFormLayout, QSizePolicy

            page = QWidget()

            # Contact info (replaces previous "应用" row)
            contact = QLabel(
                "<a href='mailto:nowaywastaken@outlook.com'>联系开发者：nowaywastaken@outlook.com</a>",
                page,
            )
            contact.setGeometry(0, 0, 318, 36)
            contact.setOpenExternalLinks(True)

            # Progress bar (absolute positioning) -> move below log_view
            self.progress_bar = QProgressBar(page)
            self.progress_bar.setGeometry(0, 480, 318, 20)
            try:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setTextVisible(False)
                # Use explicit background-color to ensure chunks render correctly across platforms
                self.progress_bar.setStyleSheet(
                    "QProgressBar{background-color:#e5e7eb;border:1px solid #d1d5db;height:20px;}"
                    "QProgressBar::chunk{background-color:#4C7DFF;}"
                )
            except Exception:
                pass
            # Ensure the progress bar is not obscured by other widgets
            try:
                self.progress_bar.raise_()
            except Exception:
                pass

            # Status label for progress text (move above progress bar)
            self.progress_label = QLabel("", page)
            self.progress_label.setGeometry(0, 460, 318, 16)
            self.progress_label.setStyleSheet("font-size:11px;color:#6b7280;")
            try:
                self.progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            except Exception:
                pass
            self.progress_label.setVisible(True)

            # Replace log area with Export settings form
            export_panel = QWidget(page)
            export_panel.setGeometry(0, 40, 318, 410)
            form = QFormLayout()
            try:
                form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            except Exception:
                pass
            export_panel.setLayout(form)

            # Labels for export-related fields
            _export_labels = {
                "run_export": "运行后导出",
                "export_split": "按篇导出",
                "export_order": "段落顺序",
                "export_mono": "仅中文",
                "export_out_dir": "导出目录",
                "export_first_line_indent_cm": "首行缩进(厘米)",
                "export_font_zh_name": "中文字体",
                "export_font_zh_size": "中文字号",
                "export_font_en_name": "英文字体",
                "export_font_en_size": "英文字号",
                "export_title_bold": "标题加粗",
                "export_title_size_multiplier": "标题字号倍率",
            }

            # Helper to add a field bound to config change handler
            def _add_field(key: str) -> None:
                if key not in self.config:
                    return
                editor = QLineEdit(export_panel)
                editor.setText(str(self.config.get(key)))
                try:
                    sp = editor.sizePolicy()
                    sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
                    editor.setSizePolicy(sp)
                except Exception:
                    pass
                editor.editingFinished.connect(lambda k=key, e=editor: self._on_conf_changed(k, e.text()))
                lbl = QLabel(_export_labels.get(key, key))
                try:
                    lbl.setFixedWidth(120)
                    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                except Exception:
                    pass
                form.addRow(lbl, editor)

            for k in [
                "run_export",
                "export_split",
                "export_order",
                "export_mono",
                "export_out_dir",
                "export_first_line_indent_cm",
                "export_font_zh_name",
                "export_font_zh_size",
                "export_font_en_name",
                "export_font_en_size",
                "export_title_bold",
                "export_title_size_multiplier",
            ]:
                _add_field(k)

            # Ensure progress widgets are above the log view and links (z-order)
            try:
                self.progress_bar.raise_()
                self.progress_label.raise_()
            except Exception:
                pass

            # Realtime logging to file only; UI log removed
            self._log_tail_pos = 0
            self._log_path = str(Path.cwd() / "log.txt")
            self._timer = QTimer(self)
            
            return page

        def _build_settings_page(self, conf: Dict[str, Any]) -> QWidget:
            # Editable settings grouped into categories with pagination via QStackedLayout

            import yaml
            from PyQt6.QtWidgets import QLineEdit, QSizePolicy

            page = QWidget()
            # Settings page now only contains Scrape/Process; no category bar
            # Keep internal structure with a single logical category key
            cats = [("", "scrape_process")]
            self._cat_links = []

            # Pages container
            container = QWidget(page)
            container.setGeometry(0, 0, 318, 504)
            sub_stack = QStackedLayout()
            container.setLayout(sub_stack)

            # Compute UI width/height for settings area and log it
            try:
                ui_w = int(self.width())
                ui_h = int(self.height())
                area_w = int(container.width())
                area_h = int(container.height())
                unified_print(
                    f"ui size: window=({ui_w}x{ui_h}), settings-area=({area_w}x{area_h})",
                    "ui",
                    "layout",
                    level="info",
                )
            except Exception:
                area_w, area_h = 318, 504

            self._editors: dict[str, QLineEdit] = {}

            def flatten(prefix: str, obj: Any) -> list[tuple[str, Any]]:
                items: list[tuple[str, Any]] = []
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        key = f"{prefix}.{k}" if prefix else str(k)
                        items.extend(flatten(key, v))
                else:
                    items.append((prefix, obj))
                return items

            # Chinese label mapping for settings keys
            CN_LABELS: dict[str, str] = {
                # app/ui
                "app.name": "应用名称",
                "ui.fixed_width": "窗口宽度",
                "ui.fixed_height": "窗口高度",
                "ui.high_dpi": "高DPI",
                "ui.initial_page": "初始页",
                "ui.theme.primary_color": "主题主色",
                "ui.theme.background_color": "背景色",
                "ui.theme.text_color": "文字颜色",
                "ui.theme.accent_color": "强调色",
                "ui.theme.danger_color": "警告色",
                # scrape
                "crawler_mode": "抓取模式",
                "crawler_api_url": "抓取服务URL",
                "crawler_api_token": "抓取令牌",
                "crawler_sites_file": "站点清单文件",
                "gdelt_timespan": "GDELT时间跨度",
                "gdelt_max_per_call": "GDELT每批最大",
                "gdelt_sort": "GDELT排序",
                "max_urls": "最大URL数",
                "concurrency": "并发数",
                "retry_hours": "重试小时",
                "timeout": "超时时间(秒)",
                "strict_success": "严格成功",
                "max_api_rounds": "最大API轮次",
                "per_url_retries": "每URL重试",
                "pick_mode": "选择方式",
                "random_seed": "随机种子",
                "db_path": "缓存数据库路径",
                "noise_patterns": "噪声词",
                # process
                "openai_api_base": "模型地址",
                "openai_api_key": "模型密钥",
                "openai_model": "模型ID",
                "target_language": "目标语言",
                "merge_short_paragraph_chars": "短段合并阈值",
                # export
                "run_export": "运行后导出",
                "export_split": "按篇导出",
                "export_order": "段落顺序",
                "export_mono": "仅中文",
                "export_out_dir": "导出目录",
                "export_first_line_indent_cm": "首行缩进(厘米)",
                "export_font_zh_name": "中文字体",
                "export_font_zh_size": "中文字号",
                "export_font_en_name": "英文字体",
                "export_font_en_size": "英文字号",
                "export_title_bold": "标题加粗",
                "export_title_size_multiplier": "标题字号倍率",
            }

            def _label_for(key: str) -> str:
                return CN_LABELS.get(key, key)

            def categorize(key: str) -> str:
                if key.startswith("app."):
                    return "app"
                if key.startswith("ui."):
                    return "ui"
                if key.startswith("export_") or key in {"run_export"}:
                    return "export"
                if key.startswith("openai_") or key in {
                    "target_language",
                    "merge_short_paragraph_chars",
                }:
                    return "process"
                if (
                    key.startswith("crawler_")
                    or key.startswith("gdelt_")
                    or key
                    in {
                        "max_urls",
                        "concurrency",
                        "retry_hours",
                        "timeout",
                        "strict_success",
                        "max_api_rounds",
                        "per_url_retries",
                        "pick_mode",
                        "random_seed",
                        "db_path",
                        "noise_patterns",
                    }
                ):
                    return "scrape"
                return "other"

            pairs = [p for p in flatten("", conf) if p[0]]
            groups: dict[str, list[tuple[str, Any]]] = {c[1]: [] for c in cats}
            for key, val in pairs:
                groups.setdefault(categorize(key), []).append((key, val))

            # Build each category page (with filtering rules applied)
            cat_to_index: dict[str, int] = {}
            for cat_key in [c[1] for c in cats]:
                w = QWidget()
                f = QFormLayout()
                f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
                # Make second column (fields) grow to use available width
                try:
                    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
                except Exception:
                    pass
                w.setLayout(f)
                # Build items for each visible category
                if cat_key == "scrape_process":
                    # Merge: keep limited scrape keys + full process keys
                    scrape_pairs = list(groups.get("scrape", []))
                    allowed_scrape = {
                        "crawler_mode",
                        "crawler_api_url",
                        "crawler_api_token",
                        "noise_patterns",
                    }
                    scrape_pairs = [(k, v) for (k, v) in scrape_pairs if k in allowed_scrape]
                    process_pairs = list(groups.get("process", []))
                    pairs_in_cat = scrape_pairs + process_pairs
                elif cat_key in {"app", "ui", "other"}:
                    pairs_in_cat = []
                else:
                    pairs_in_cat = list(groups.get(cat_key, []))

                # Determine label and field widths based on available area
                label_fixed_w = 96  # keep labels compact to widen field column
                field_min_w = max(80, int(area_w) - label_fixed_w - 24)

                for key, val in pairs_in_cat:
                    editor = QLineEdit(w)
                    # For noise_patterns, present without brackets, joined by Chinese comma
                    if key == "noise_patterns" and isinstance(val, list):
                        try:
                            editor.setText("，".join([str(x) for x in val]))
                        except Exception:
                            editor.setText(str(val))
                    else:
                        editor.setText(str(val))
                    # Ensure the field grows and is minimally wide
                    try:
                        sp = editor.sizePolicy()
                        sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
                        sp.setVerticalPolicy(QSizePolicy.Policy.Fixed)
                        editor.setSizePolicy(sp)
                    except Exception:
                        pass
                    try:
                        editor.setMinimumWidth(field_min_w)
                    except Exception:
                        pass
                    editor.editingFinished.connect(
                        lambda k=key, e=editor: self._on_conf_changed(k, e.text())
                    )
                    lbl = QLabel(_label_for(key))
                    try:
                        lbl.setFixedWidth(label_fixed_w)
                        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    except Exception:
                        pass
                    f.addRow(lbl, editor)
                    self._editors[key] = editor
                cat_to_index[cat_key] = sub_stack.count()
                sub_stack.addWidget(w)

            # No category links to handle

            self._yaml_dump = lambda data: yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            return page

        def _thread_target(self, mode: str) -> None:
            try:
                if mode == "all":
                    # Override max_urls by UI input if provided
                    cfg = dict(self.config)
                    try:
                        n = self._get_count_value()
                        if n and n > 0:
                            cfg["max_urls"] = n
                    except Exception:
                        pass
                    s = run_scrape(cfg)
                    p = run_process(self.config, s)
                    run_export(self.config, p)
                    # Auto-clean the run directory after successful export
                    try:
                        from pathlib import Path as _P

                        run_dir = _P(p).parent
                        # best-effort removal of processed/scraped and the directory
                        for name in ("processed.json", "scraped.json"):
                            try:
                                (_P(run_dir) / name).unlink(missing_ok=True)
                            except Exception:
                                pass
                        # attempt to remove the run directory if empty
                        try:
                            next(run_dir.iterdir())
                        except StopIteration:
                            try:
                                run_dir.rmdir()
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception as e:
                unified_print(f"run error: {e}", "ui", "error", level="error")

        def _find_latest(self, pattern: str) -> Optional[str]:
            from pathlib import Path

            paths = sorted(Path.cwd().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            return str(paths[0]) if paths else None

        def _launch(self, mode: str) -> None:
            t = threading.Thread(target=self._thread_target, args=(mode,), daemon=True)
            t.start()

        def _on_run_all(self) -> None:
            unified_print("one-click run", "ui", "action", level="info")
            # Start QThread worker that drives progress via signals
            try:
                self._start_worker_all()
            except Exception as e:
                # fallback to legacy thread if Qt thread fails
                unified_print(f"worker start failed: {e}; fallback thread", "ui", "error", level="error")
                self._launch("all")

        def _start_worker_all(self) -> None:
            from PyQt6.QtCore import QThread, pyqtSignal

            class ProgressWorker(QThread):
                progressChanged = pyqtSignal(int, str)
                finishedWithStatus = pyqtSignal(bool, str)

                def __init__(self, ui: "MainWindow", conf: Dict[str, Any], count_override: Optional[int]) -> None:
                    super().__init__(ui)
                    self.ui = ui
                    self.conf = dict(conf)
                    if count_override and count_override > 0:
                        self.conf["max_urls"] = int(count_override)
                    self._stop = False

                def _emit(self, v: int, text: str) -> None:
                    self.progressChanged.emit(int(v), str(text))

                def _slow_ramp(self, start: int, end: int, step: int, interval: float) -> None:
                    cur = int(start)
                    target = int(end)
                    stepv = max(1, int(step))
                    while not self._stop and cur < target:
                        cur = min(target, cur + stepv)
                        self._emit(cur, self._last_text)
                        import time as _t

                        _t.sleep(max(0.05, float(interval)))

                def run(self) -> None:  # type: ignore[override]
                    import time as _time
                    ok = False
                    msg = ""
                    try:
                        # Stage: scrape
                        self._last_text = "开始抓取网页…"
                        self._emit(0, self._last_text)
                        spath = run_scrape(self.conf)
                        self._emit(25, "抓取完成")

                        # Stage: process (simulate ramp while running)
                        self._emit(30, "正在处理内容…")

                        import threading as _th

                        processed_path: Dict[str, Optional[str]] = {"p": None}

                        def _do_process() -> None:
                            try:
                                processed_path["p"] = run_process(self.conf, spath)
                            except Exception as _e:
                                processed_path["p"] = None
                                raise _e

                        t = _th.Thread(target=_do_process, daemon=True)
                        t.start()
                        self._last_text = "翻译进行中…"
                        cur = 35
                        self._emit(cur, self._last_text)
                        while t.is_alive():
                            cur = min(85, cur + 1)
                            self._emit(cur, self._last_text)
                            _time.sleep(0.35)
                        ppath = processed_path["p"] or ""
                        self._emit(90, "保存结果…")

                        # Stage: export (slow ramp)
                        def _do_export() -> None:
                            run_export(self.conf, ppath)

                        te = _th.Thread(target=_do_export, daemon=True)
                        te.start()
                        self._last_text = "导出文件…"
                        cur = 92
                        self._emit(cur, self._last_text)
                        while te.is_alive():
                            cur = min(98, cur + 1)
                            self._emit(cur, self._last_text)
                            _time.sleep(0.5)
                        self._emit(100, "全部完成！")
                        ok = True
                    except Exception as e:
                        msg = str(e)
                    finally:
                        self.finishedWithStatus.emit(ok, msg)

            # Retrieve optional count override
            count_override: Optional[int] = None
            try:
                s = self.input_count_edit.text().strip()
                count_override = int(s) if s else None
            except Exception:
                count_override = None

            self._worker = ProgressWorker(self, self.config, count_override)
            self._worker.progressChanged.connect(self._on_progress_changed)
            self._worker.finishedWithStatus.connect(self._on_worker_finished)
            self._worker.start()

        def _on_progress_changed(self, value: int, text: str) -> None:
            try:
                self.progress_bar.setValue(int(value))
                if text:
                    self.progress_label.setText(str(text))
                if not self.progress_label.isVisible():
                    self.progress_label.setVisible(True)
            except Exception:
                pass

        def _on_worker_finished(self, ok: bool, message: str) -> None:
            if ok:
                unified_print("run finished", "ui", "action", level="info")
            else:
                unified_print(f"run failed: {message}", "ui", "error", level="error")

        # --- Count stepper helpers ---
        def _get_count_value(self) -> int:
            """Return current count displayed in the stepper (>=1)."""
            try:
                v = int(str(self.input_count_display.text()).strip() or "1")
            except Exception:
                v = 1
            if v < 1:
                v = 1
            return v

        def _set_count_value(self, v: int) -> None:
            """Set the count display; keeps range [1, 999]."""
            try:
                if v < 1:
                    v = 1
                if v > 999:
                    v = 999
                self.input_count_display.setText(str(int(v)))
                unified_print(f"count set -> {v}", "ui", "action", level="info")
            except Exception:
                pass

        def _adjust_count(self, delta: int) -> None:
            """Increment or decrement count by delta; min=1, max=999."""
            try:
                cur = self._get_count_value()
                self._set_count_value(cur + int(delta))
            except Exception:
                pass

        # settings change handler: write through to config.yml
        def _on_conf_changed(self, key: str, value: str) -> None:
            try:
                # update in-memory dict by dot key
                parts = key.split(".")
                ref = self.config
                for p in parts[:-1]:
                    if p not in ref or not isinstance(ref[p], dict):
                        ref[p] = {}
                    ref = ref[p]
                # try convert types from original
                orig = ref.get(parts[-1]) if isinstance(ref, dict) else None
                # Special handling: noise_patterns supports comma or Chinese comma separated items
                if parts[-1] == "noise_patterns":
                    s = (value or "").strip()
                    if s == "":
                        new_val = []
                    else:
                        # Accept both ',' and '，' as separators; trim spaces; drop empties
                        tokens = [t.strip() for t in s.replace("，", ",").split(",")]
                        new_val = [t for t in tokens if t]
                    ref[parts[-1]] = new_val
                    Path("config.yml").write_text(self._yaml_dump(self.config), encoding="utf-8")
                    unified_print(
                        f"config saved: noise_patterns -> {new_val}", "ui", "config", level="info"
                    )
                    return
                new_val: Any = value
                if isinstance(orig, bool):
                    new_val = str(value).strip().lower() in {"1", "true", "yes", "on"}
                elif isinstance(orig, int):
                    try:
                        new_val = int(value)
                    except Exception:
                        pass
                elif isinstance(orig, float):
                    try:
                        new_val = float(value)
                    except Exception:
                        pass
                ref[parts[-1]] = new_val
                # write back to config.yml
                Path("config.yml").write_text(self._yaml_dump(self.config), encoding="utf-8")
                unified_print(f"config saved: {key} -> {new_val}", "ui", "config", level="info")
            except Exception as e:
                unified_print(f"config save error: {e}", "ui", "error", level="error")

        # --- Progress & log bridge ---
        def _install_log_bridge(self) -> None:
            import logging

            from PyQt6.QtCore import QTimer

            # Signals created dynamically on instance to keep minimal churn
            # Using simple callables instead of defining pyqtSignal at class level
            self._progress_value = 0  # 0-100 integer
            self._progress_target = 0
            self._progress_step = 1  # units per tick
            self._phase = "idle"
            self._total_articles = 0
            self._done_articles = 0

            def _set_target(v: int, step: int, phase: str, label: str) -> None:
                v = max(0, min(100, int(v)))
                self._progress_target = v
                self._progress_step = max(1, int(step))
                self._phase = phase
                try:
                    # Hide percent numbers; keep optional status text only
                    self.progress_label.setText(label)
                except Exception:
                    pass
                # Immediate, minimal forward bump to ensure visible movement even if timer stalls
                try:
                    delta = int(v) - int(self._progress_value)
                    if delta > 0:
                        bump = 5 if delta >= 15 else 1
                        self._progress_value = min(int(v), int(self._progress_value) + bump)
                        self.progress_bar.setValue(int(self._progress_value))
                        # Force immediate paint for better responsiveness
                        from PyQt6.QtCore import QCoreApplication as _QApp

                        _QApp.processEvents()
                except Exception:
                    pass

            # Animation timer
            self._progress_anim = QTimer(self)
            self._progress_anim.setInterval(50)

            def _tick() -> None:
                try:
                    if self._progress_value < self._progress_target:
                        self._progress_value = min(
                            self._progress_target, self._progress_value + self._progress_step
                        )
                        self.progress_bar.setValue(self._progress_value)
                        # Do not render percent numbers in label
                except Exception:
                    pass

            self._progress_anim.timeout.connect(_tick)
            self._progress_anim.start()

            class _UiLogHandler(logging.Handler):
                def __init__(self, ui: "MainWindow") -> None:
                    super().__init__()
                    self.ui = ui
                    # open file in append mode, UTF-8
                    try:
                        self.fp = open(self.ui._log_path, "a", encoding="utf-8")
                    except Exception:
                        self.fp = None

                def emit(self, record: logging.LogRecord) -> None:
                    try:
                        from PyQt6.QtCore import QTimer as _QTimer

                        msg = record.getMessage()
                        name = record.name or ""
                        # Build a compact line similar to unified_print echo
                        parts = name.split(".")
                        program = parts[1] if len(parts) > 1 else ""
                        task = parts[2] if len(parts) > 2 else ""
                        line = f"[{program}][{task}] {msg}".strip()

                        # Always write to file from this thread
                        if self.fp:
                            try:
                                self.fp.write(line + "\n")
                                self.fp.flush()
                            except Exception:
                                pass

                        # UI updates must occur on the Qt main thread
                        def _apply_ui() -> None:
                            try:
                                # append to UI log
                                self.ui.log_view.append(line)
                            except Exception:
                                pass

                        # Progress mapping (safe inside UI thread)
                        # Optionally disabled when Worker drives progress
                        if not getattr(self.ui, "_use_log_bridge_progress", False):
                            return
                            lprog = program
                            ltask = task
                            text = msg
                            # 1) Scrape phase 0-25 (uniform)
                            if lprog == "ui" and ltask == "scrape" and "scrape start" in text:
                                self.ui._progress_value = 0
                                _set_target(25, 1, "scrape", "抓取中…")
                            if lprog == "ui" and ltask == "scrape" and text.startswith("scrape saved"):
                                _set_target(25, 2, "scrape", "抓取完成")

                            # Be robust to non-UI scrape logs
                            if lprog == "scrape" and ltask == "run" and "[TASK START]" in text:
                                self.ui._progress_value = 0
                                _set_target(20, 1, "scrape", "抓取中…")
                            if lprog == "scrape" and ltask == "run" and "[TASK END]" in text:
                                _set_target(25, 2, "scrape", "抓取完成")

                            # 2) Process phase start 30%
                            if lprog == "ui" and ltask == "process" and "process start" in text:
                                _set_target(30, 1, "process", "准备处理…")

                            # 2.1) Batch start to get total count
                            if lprog == "engine" and ltask == "batch" and "[TASK START]" in text:
                                try:
                                    import json as _json

                                    payload = text.split("[TASK START]")[-1].strip()
                                    data = _json.loads(payload)
                                    self.ui._total_articles = int(data.get("count") or 0)
                                except Exception:
                                    self.ui._total_articles = 0

                            # 2.2) Article processing and results -> 35%..85%
                            if lprog == "engine" and ltask == "article" and "processing article" in text:
                                base = max(self.ui._progress_target, 35)
                                _set_target(base, 1, "process", "处理中…")

                            if lprog == "engine" and ltask == "article" and text.startswith("[RESULT]"):
                                self.ui._done_articles += 1
                                total = max(1, int(self.ui._total_articles or 1))
                                ratio = max(0.0, min(1.0, float(self.ui._done_articles) / float(total)))
                                target = int(35 + (85 - 35) * ratio)
                                step = 2 if (target - self.ui._progress_value) > 5 else 1
                                _set_target(
                                    target, step, "process", f"处理中…({self.ui._done_articles}/{total})"
                                )

                            # 3) Process saved 90%
                            if lprog == "ui" and ltask == "process" and text.startswith("processed saved"):
                                _set_target(90, 1, "process", "处理结果已保存")
                            if lprog == "engine" and ltask == "batch" and "[TASK END]" in text:
                                # Batch completes -> close to export phase
                                _set_target(90, 1, "process", "处理结果已保存")

                            # 4) Export 92% start, slow approach to 100
                            if lprog == "ui" and ltask == "export" and text.startswith("export start"):
                                _set_target(92, 1, "export", "导出中…")

                            # export docx events -> move close to 98
                            if lprog == "export" and ltask == "docx" and text.startswith("Exported DOCX"):
                                target2 = max(self.ui._progress_target, 98)
                                _set_target(target2, 1, "export", "导出进行中…")

                            # export done -> 100
                            if lprog == "ui" and ltask == "export" and text.startswith("export per-article"):
                                _set_target(100, 4, "done", "全部导出完成")
                            if lprog == "ui" and ltask == "export" and text.startswith("export single"):
                                _set_target(100, 4, "done", "导出完成")

                        # Post the UI update to main thread event loop
                        _QTimer.singleShot(0, _apply_ui)
                    except Exception:
                        pass

                def close(self) -> None:  # type: ignore[override]
                    try:
                        if self.fp:
                            self.fp.close()
                    except Exception:
                        pass
                    super().close()

            # Attach handler to root logger once
            try:
                root = logging.getLogger("")
                # ensure handler is not duplicated across UI reloads
                if not any(isinstance(h, _UiLogHandler) for h in root.handlers):
                    root.addHandler(_UiLogHandler(self))
            except Exception:
                pass

        def _poll_log(self) -> None:
            from pathlib import Path

            try:
                p = Path(self._log_path)
                if not p.exists():
                    return
                data = p.read_bytes()
                if self._log_tail_pos > len(data):
                    self._log_tail_pos = 0
                chunk = data[self._log_tail_pos :]
                if chunk:
                    try:
                        text = chunk.decode("utf-8", errors="ignore")
                    except Exception:
                        text = ""
                    if text:
                        self.log_view.append(text)
                    self._log_tail_pos = len(data)
            except Exception:
                pass

        def _open_log_file(self) -> None:
            try:
                import webbrowser

                webbrowser.open(self._log_path)
            except Exception:
                pass

        def _open_terminal_log(self) -> None:
            try:
                import platform
                import subprocess

                logp = self._log_path
                if platform.system().lower().startswith("win"):
                    CREATE_NEW_CONSOLE = 0x00000010
                    subprocess.Popen(["cmd", "/k", "type", logp], creationflags=CREATE_NEW_CONSOLE)
                elif platform.system().lower() == "darwin":
                    # Open Terminal and tail log
                    os.system(f'osascript -e \'tell app "Terminal" to do script "tail -f {logp}"\'')
                else:
                    subprocess.Popen(["x-terminal-emulator", "-e", "tail", "-f", logp])
            except Exception:
                pass

    # High DPI setup
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    try:
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    prepare_logging("log.txt")
    conf = load_app_config("config.yml")
    app = QApplication(sys.argv)
    w = MainWindow(conf)
    w.show()
    unified_print("ui shown", "ui", "startup", level="info")
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()
