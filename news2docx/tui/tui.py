from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
import json as _json
import ast as _ast

# Reuse existing orchestration and helpers from index.py to avoid duplication
from index import load_app_config, prepare_logging, run_export, run_process, run_scrape
from news2docx.ai.selector import SILICON_BASE, free_chat_models
from news2docx.cli.common import ensure_openai_env
from news2docx.services.runs import runs_base_dir

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


console = Console(highlight=False)

_last_ctx: Dict[str, Any] = {}


def _one_click(conf: Dict[str, Any]) -> None:
    """Run scrape -> process -> export with a simple overall progress bar."""
    _last_ctx.clear()
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]阶段[/]: {task.fields[stage]}", justify="left"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("run", total=100, stage="准备中…")

            # Stage 1: scrape
            progress.update(task, stage="抓取网页…", advance=0)
            try:
                scraped_path = run_scrape(conf)
                _last_ctx["scraped"] = scraped_path
                _last_ctx["stage"] = "scrape_done"
            except Exception as e:
                _last_ctx["failed_stage"] = "scrape"
                progress.update(task, stage="抓取失败")
                console.print(Panel.fit(str(e), title="错误", style="bold red"))
                return
            progress.update(task, advance=30, stage="抓取完成")

            # Stage 2: process (run in a thread, slowly advance up to 85)
            processed_path: Dict[str, Optional[str]] = {"p": None}

            def _do_process() -> None:
                try:
                    processed_path["p"] = run_process(conf, scraped_path)
                except Exception:
                    processed_path["p"] = None

            t = threading.Thread(target=_do_process, daemon=True)
            progress.update(task, stage="处理与翻译…")
            t.start()
            cur = 30
            while t.is_alive():
                time.sleep(0.3)
                cur = min(85, cur + 1)
                progress.update(task, completed=cur)
            if not processed_path["p"]:
                _last_ctx["failed_stage"] = "process"
                progress.update(task, stage="处理失败")
                console.print(
                    Panel.fit("处理阶段失败，请查看 log.txt", title="错误", style="bold red")
                )
                return
            _last_ctx["processed"] = processed_path["p"]
            _last_ctx["stage"] = "process_done"
            progress.update(task, completed=90, stage="保存结果…")

            # Stage 3: export (thread + slow advance to 100)
            export_done: Dict[str, Optional[str]] = {"out": None}

            def _do_export() -> None:
                try:
                    export_done["out"] = run_export(conf, processed_path["p"] or "")
                except Exception:
                    export_done["out"] = None

            te = threading.Thread(target=_do_export, daemon=True)
            progress.update(task, stage="导出 DOCX…")
            te.start()
            cur = 90
            while te.is_alive():
                time.sleep(0.4)
                cur = min(99, cur + 1)
                progress.update(task, completed=cur)
            if export_done["out"]:
                _last_ctx["out"] = export_done["out"]
                _last_ctx["stage"] = "done"
                progress.update(task, completed=100, stage="完成")
                console.print(
                    Panel.fit(f"导出完成: {export_done['out']}", title="成功", style="bold green")
                )
            else:
                _last_ctx["failed_stage"] = "export"
                progress.update(task, stage="导出失败")
                console.print(
                    Panel.fit("导出阶段失败，请查看 log.txt", title="错误", style="bold red")
                )
    except KeyboardInterrupt:
        _last_ctx["failed_stage"] = _last_ctx.get("stage", "unknown")
        console.print(Panel.fit("已取消当前操作", title="中断", style="yellow"))


def _one_click_with_mode(conf: Dict[str, Any], mode: str) -> None:
    # Set pipeline mode for this run
    import os as _os

    _os.environ["N2D_PIPELINE_MODE"] = mode
    _one_click(conf)


def _doctor(conf: Dict[str, Any]) -> None:
    """Basic health checks: API key, SiliconFlow endpoint, export dir, runs dir."""
    ok = True
    msgs: list[str] = []

    # API key (SiliconFlow preferred)
    key = (
        os.getenv("SILICONFLOW_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or conf.get("openai_api_key")
    )
    if not key:
        ok = False
        msgs.append("缺少 API Key（SILICONFLOW_API_KEY 或 OPENAI_API_KEY）")

    # Reachability: SiliconFlow base and models
    base = SILICON_BASE
    try:
        root_resp = requests.head(base, timeout=5, allow_redirects=True)
        code_root = root_resp.status_code
        try:
            m_resp = requests.get(f"{base}/models", timeout=8)
            code_models = m_resp.status_code
        except Exception:
            code_models = None
        if (200 <= code_root < 400 or code_root in {401, 403}) and (code_models in {200, 401, 403}):
            msgs.append(
                f"SiliconFlow 在线：HEAD {code_root}；/models {code_models if code_models is not None else 'N/A'}"
            )
        else:
            ok = False
            msgs.append(
                f"SiliconFlow 不可达或错误：HEAD {code_root}；/models {code_models if code_models is not None else 'N/A'}"
            )
    except Exception as e:
        ok = False
        msgs.append(f"SiliconFlow 探测失败：{e}")

    # Show discovered free models
    try:
        ms = free_chat_models()
        msgs.append(f"可用免费模型（筛）：{', '.join(ms)}")
    except Exception:
        pass

    # Export directory
    try:
        from news2docx.cli.common import desktop_outdir

        outdir = desktop_outdir()
        msgs.append(f"导出目录：{outdir}")
    except Exception as e:
        ok = False
        msgs.append(f"导出目录不可用：{e}")

    # Runs directory
    try:
        base_dir = runs_base_dir(conf)
        base_dir.mkdir(parents=True, exist_ok=True)
        msgs.append(f"runs 目录：{base_dir}")
    except Exception as e:
        ok = False
        msgs.append(f"runs 目录不可用：{e}")

    style = "bold green" if ok else "bold red"
    title = "体检通过" if ok else "体检失败"
    console.print(Panel("\n".join(msgs), title=title, style=style))


def _bool_parse(v: str) -> Optional[bool]:
    s = (v or "").strip().lower()
    if s in {"", None}:
        return None
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError("无效布尔值，仅接受 yes/no/true/false/1/0")


def _float_parse(v: str) -> Optional[float]:
    s = (v or "").strip()
    if s == "":
        return None
    return float(s)


def _list_parse(v: str) -> Optional[list[str]]:
    s = (v or "").strip()
    if s == "":
        return None
    # Accept JSON-like or Python-like list representations first
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
        try:
            try:
                val = _json.loads(s)
            except Exception:
                val = _ast.literal_eval(s)
            if isinstance(val, (list, tuple)):
                return [str(x).strip().strip("\"'") for x in val if str(x).strip()]
        except Exception:
            pass
    # Fallback: comma-separated into list; strip quotes/brackets artifacts
    parts = [i.strip() for i in s.split(",") if i.strip()]
    cleaned = []
    for p in parts:
        pp = p.strip().strip("[](){}").strip().strip("\"'")
        if pp:
            cleaned.append(pp)
    return cleaned


def _normalize_list_value(v: Any) -> list[str]:
    out: list[str] = []

    def _add_one(x: Any) -> None:
        s = str(x) if not isinstance(x, str) else x
        s = s.strip()
        if not s:
            return
        # If looks like a list encoded as a single string, try to parse
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
            try:
                try:
                    val = _json.loads(s)
                except Exception:
                    val = _ast.literal_eval(s)
                if isinstance(val, (list, tuple)):
                    for y in val:
                        _add_one(y)
                    return
            except Exception:
                pass
        # Strip surrounding quotes once
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        if s and s not in out:
            out.append(s)

    if isinstance(v, (list, tuple)):
        for item in v:
            _add_one(item)
    elif isinstance(v, str):
        lv = _list_parse(v)
        if lv is not None:
            for item in lv:
                _add_one(item)
    return out


def _config_menu(conf_path: Path, conf: Dict[str, Any]) -> Dict[str, Any]:
    """Config editor aligned with config.example.yml.

    - Empty input keeps current value.
    - Enforces HTTPS for openai_api_base.
    - Persists to config.yml (UTF-8, keep key order).
    """
    if yaml is None:
        console.print(Panel.fit("缺少 PyYAML 依赖，无法编辑配置。", title="错误", style="bold red"))
        return conf

    # 精简后的可编辑字段
    fields: list[tuple[str, str, str]] = [
        ("openai_api_key", "secret", "API Key (用于 SiliconFlow)"),
        ("processing_word_min", "int", "英文原文字数下限 (硬性)"),
        ("processing_forbidden_prefixes", "list", "过滤前缀（逗号分隔）"),
        ("processing_forbidden_patterns", "list", "过滤正则（逗号分隔）"),
        ("export_font_zh_name", "str", "中文字体名"),
        ("export_font_zh_size", "float", "中文字号（pt）"),
        ("export_font_en_name", "str", "英文字体名"),
        ("export_font_en_size", "float", "英文字号（pt）"),
        ("export_title_bold", "bool", "标题加粗（true/false）"),
    ]

    console.print(
        Panel.fit(
            "配置编辑器：回车保留当前值，输入新值后回车保存该项。", title="配置", style="cyan"
        )
    )
    updated: Dict[str, Any] = dict(conf)

    for key, typ, label in fields:
        cur = updated.get(key)
        if typ == "list":
            cur_list = _normalize_list_value(cur)
            updated[key] = cur_list
            shown = ", ".join(cur_list)
        else:
            shown = (
                "*****"
                if (key == "openai_api_key" and cur)
                else (str(cur) if cur is not None else "")
            )
        try:
            new_val = Prompt.ask(f"{label} [{key}]", default="" if typ == "secret" else shown)
        except (KeyboardInterrupt, EOFError):
            console.print(Panel.fit("已取消配置编辑。", title="中断", style="yellow"))
            return updated

        if new_val is None or new_val.strip() == "":
            continue  # keep existing

        try:
            if typ == "int":
                updated[key] = int(new_val)
            elif typ == "float":
                fv = _float_parse(new_val)
                if fv is None:
                    continue
                updated[key] = fv
            elif typ == "bool":
                b = _bool_parse(new_val)
                if b is None:
                    continue
                updated[key] = b
            elif typ == "list":
                lv = _list_parse(new_val)
                if lv is None:
                    continue
                updated[key] = _normalize_list_value(lv)
            elif typ == "secret":
                updated[key] = new_val.strip()
            else:  # str
                updated[key] = new_val.strip()
        except Exception as e:
            console.print(Panel.fit(f"{key} 无法解析：{e}", title="错误", style="bold red"))

    # API Base 与模型由代码自动管理，此处无需处理

    # Persist to YAML
    try:
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        with conf_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(updated, f, allow_unicode=True, sort_keys=False)
        console.print(Panel.fit(f"已保存到 {conf_path}", title="成功", style="bold green"))
    except Exception as e:
        console.print(Panel.fit(f"写入配置失败：{e}", title="错误", style="bold red"))
        return conf

    # Refresh env for current session
    try:
        ensure_openai_env(updated)
    except Exception:
        pass

    return updated


def main() -> None:
    """Entry for Rich-based TUI."""
    console.print(Panel.fit("News2Docx TUI (Rich)", style="cyan", title="UI"))
    # init logging and load config
    prepare_logging("log.txt")
    conf = load_app_config("config.yml")
    # Mandatory health check at startup
    _doctor(conf)

    while True:
        console.print("选择操作：")
        console.print("  1) 免费白嫖通道（抓取→筛选→清洗→合并→翻译→导出）")
        console.print("  2) 付费快速通道（抓取→检查→清洗→调整→合并→翻译→导出）")
        console.print("  3) 配置（查看/修改 config.yml）")
        console.print("  4) 体检（检查网络与配置）")
        console.print("  5) 退出")
        try:
            choice = Prompt.ask("输入选项", default="1").strip().lower()
        except KeyboardInterrupt:
            console.print(Panel.fit("已退出", title="中断", style="yellow"))
            return
        except EOFError:
            # 非交互环境：直接退出，避免噪声日志
            console.print(Panel.fit("无交互终端，已退出。", title="提示", style="yellow"))
            return

        if choice == "1":
            _one_click_with_mode(conf, "free")
        elif choice == "2":
            _one_click_with_mode(conf, "paid")
        elif choice == "3":
            conf = _config_menu(Path("config.yml"), conf)
        elif choice == "4":
            _doctor(conf)
        elif choice == "5":
            break
        else:
            console.print("无效选项，请重试。")


if __name__ == "__main__":
    main()
