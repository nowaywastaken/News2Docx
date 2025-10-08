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

            # Count input (left of run button)
            self.input_count = QLabel("数量", self)
            self.input_count.setGeometry(170, 36, 28, 24)
            from PyQt6.QtWidgets import QLineEdit

            self.input_count_edit = QLineEdit(self)
            self.input_count_edit.setGeometry(200, 36, 54, 24)
            self.input_count_edit.setPlaceholderText("1,2,3...")

            # Single action button: one-click run
            self.btn_run_all = QPushButton("一键运行", self)
            self.btn_run_all.setGeometry(260, 36, 72, 28)

            self.container = QWidget(self)
            self.container.setGeometry(16, 80, 318, 504)
            self.stack = QStackedLayout()
            self.container.setLayout(self.stack)

            self.page_home = self._build_home_page()
            self.page_settings = self._build_settings_page(self.config)
            self.stack.addWidget(self.page_home)
            self.stack.addWidget(self.page_settings)
            self.stack.setCurrentIndex(int(self.config.get("ui", {}).get("initial_page") or 0))

            self.link_home.linkActivated.connect(lambda _: self.stack.setCurrentIndex(0))
            self.link_settings.linkActivated.connect(lambda _: self.stack.setCurrentIndex(1))
            self.btn_run_all.clicked.connect(self._on_run_all)

            unified_print("ui ready", "ui", "startup", level="info")

        def _build_home_page(self) -> QWidget:
            from pathlib import Path

            page = QWidget()

            # Contact info (replaces previous "应用" row)
            contact = QLabel(
                "<a href='mailto:nowaywastaken@outlook.com'>联系开发者：nowaywastaken@outlook.com</a>",
                page,
            )
            contact.setGeometry(0, 0, 318, 36)
            contact.setOpenExternalLinks(True)

            self.log_view = QTextEdit(page)
            # Expand log area upward a bit (start higher, taller)
            self.log_view.setGeometry(0, 40, 318, 464)
            self.log_view.setReadOnly(True)
            self.log_view.setStyleSheet(
                "background-color: #ffffff; border: 1px solid #e5e7eb; font-family: Consolas, monospace; font-size: 11px;"
            )

            # Terminal log entry links
            self.link_open_log = QLabel("<a href='#openlog'>打开日志文件</a>", page)
            self.link_open_log.setGeometry(0, 508, 100, 18)
            self.link_open_log.setOpenExternalLinks(False)
            self.link_terminal_log = QLabel("<a href='#termlog'>终端查看日志</a>", page)
            self.link_terminal_log.setGeometry(108, 508, 110, 18)
            self.link_terminal_log.setOpenExternalLinks(False)

            self.link_open_log.linkActivated.connect(lambda _: self._open_log_file())
            self.link_terminal_log.linkActivated.connect(lambda _: self._open_terminal_log())

            self._log_tail_pos = 0
            self._log_path = str(Path.cwd() / "log.txt")
            # File logging is disabled; keep timer inert if file absent
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll_log)
            self._timer.start(1000)

            return page

        def _build_settings_page(self, conf: Dict[str, Any]) -> QWidget:
            # Editable settings grouped into categories with pagination via QStackedLayout

            import yaml
            from PyQt6.QtWidgets import QLineEdit

            page = QWidget()
            # Category links (absolute positioning)
            cat_bar = QWidget(page)
            cat_bar.setGeometry(0, 0, 318, 22)
            # Only expose minimal settings in UI:
            # - Scrape: only mode, service URL, token, noise keywords
            # - Process / Export remain visible
            # Hidden: 应用(app), 界面(ui), 其他(other)
            cats = [
                ("抓取", "scrape"),
                ("处理", "process"),
                ("导出", "export"),
            ]
            self._cat_links: list[QLabel] = []
            x = 0
            for i, (label, _k) in enumerate(cats):
                link = QLabel(f"<a href='#cat{i}'>{label}</a>", cat_bar)
                link.setGeometry(x, 0, 50, 20)
                link.setOpenExternalLinks(False)
                self._cat_links.append(link)
                x += 52

            # Pages container
            container = QWidget(page)
            container.setGeometry(0, 26, 318, 454)
            sub_stack = QStackedLayout()
            container.setLayout(sub_stack)

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
                "noise_patterns": "噪声关键词",
                # process
                "openai_api_base": "OpenAI兼容API根地址",
                "openai_api_key": "OpenAI兼容API密钥",
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
                w.setLayout(f)
                pairs_in_cat = list(groups.get(cat_key, []))
                if cat_key == "scrape":
                    allowed = {
                        "crawler_mode",
                        "crawler_api_url",
                        "crawler_api_token",
                        "noise_patterns",
                    }
                    pairs_in_cat = [(k, v) for (k, v) in pairs_in_cat if k in allowed]
                elif cat_key in {"app", "ui", "other"}:
                    pairs_in_cat = []

                for key, val in pairs_in_cat:
                    editor = QLineEdit(w)
                    editor.setText(str(val))
                    editor.editingFinished.connect(
                        lambda k=key, e=editor: self._on_conf_changed(k, e.text())
                    )
                    f.addRow(QLabel(_label_for(key)), editor)
                    self._editors[key] = editor
                cat_to_index[cat_key] = sub_stack.count()
                sub_stack.addWidget(w)

            # Link handlers
            for i, link in enumerate(self._cat_links):
                link.linkActivated.connect(lambda _=None, idx=i: sub_stack.setCurrentIndex(idx))

            self._yaml_dump = lambda data: yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            return page

        def _thread_target(self, mode: str) -> None:
            try:
                if mode == "all":
                    # Override max_urls by UI input if provided
                    cfg = dict(self.config)
                    try:
                        n = (
                            int(self.input_count_edit.text().strip())
                            if self.input_count_edit.text().strip()
                            else None
                        )
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
            self._launch("all")

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
