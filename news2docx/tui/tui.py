from __future__ import annotations

import ast as _ast
import json as _json
import json as _json2
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt

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

            # Stage 2: process（并发阶段按日志阶段数计算真实进度）
            processed_path: Dict[str, Optional[str]] = {"p": None}

            def _do_process() -> None:
                try:
                    processed_path["p"] = run_process(conf, scraped_path)
                except Exception:
                    processed_path["p"] = None

            t = threading.Thread(target=_do_process, daemon=True)
            progress.update(task, stage="处理与翻译…")
            t.start()

            log_path = Path("log.txt")
            total_files = 10
            stages = [
                "adjust done",
                "news check done",
                "clean done",
                "merge done",
                "translate done",
            ]
            done_count = 0
            done_translate = 0
            last_pos = 0

            def _scan_new_lines(text: str) -> None:
                nonlocal total_files, done_count, done_translate
                for ln in text.splitlines():
                    if "[TASK START]" in ln and "news2docx.engine.batch" in ln:
                        try:
                            js = ln.split("[TASK START]")[-1].strip()
                            obj = _json2.loads(js)
                            if isinstance(obj, dict) and isinstance(obj.get("count"), int):
                                total_files = max(1, int(obj["count"]))
                        except Exception:
                            pass
                    if "news2docx.engine.stage" in ln:
                        low = ln.lower()
                        for st in stages:
                            if st in low:
                                done_count += 1
                                if st == "translate done":
                                    done_translate += 1
                                break

            while t.is_alive():
                time.sleep(0.3)
                try:
                    if log_path.exists():
                        data = log_path.read_text(encoding="utf-8", errors="ignore")
                        if last_pos < len(data):
                            chunk = data[last_pos:]
                            last_pos = len(data)
                            _scan_new_lines(chunk)
                except Exception:
                    pass
                total_steps = total_files * len(stages)
                pct = 0 if total_steps == 0 else int(min(99, (done_count * 100) / total_steps))
                label = f"阶段 {done_count}/{total_steps}｜完成 {done_translate}/{total_files} 篇"
                progress.update(task, completed=pct, stage=label)
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


def _clear_crawled_cache(conf: Dict[str, Any]) -> None:
    """Remove crawled URL cache database to force re-scrape next runs."""
    try:
        db_path = conf.get("db_path")
        if not db_path:
            db_path = str((Path.cwd() / ".n2d_cache" / "crawled.sqlite3"))
        p = Path(str(db_path))
        if p.exists():
            p.unlink()
            console.print(Panel.fit(f"已清除缓存：{p}", title="完成", style="bold green"))
        else:
            console.print(Panel.fit(f"未发现缓存文件：{p}", title="提示", style="yellow"))
    except Exception as e:
        console.print(Panel.fit(f"清除失败：{e}", title="错误", style="bold red"))


def _one_click_with_mode(conf: Dict[str, Any], mode: str) -> None:
    # Set pipeline mode for this run
    import os as _os

    _os.environ["N2D_PIPELINE_MODE"] = mode
    _one_click(conf)


def _doctor(conf: Dict[str, Any]) -> None:
    """Basic health checks: API key, SiliconFlow endpoint, export dir, runs dir."""
    ok = True
    msgs: list[str] = []

    # 1) 网络连通性（Cloudflare）
    try:
        r = requests.get("https://1.1.1.1/cdn-cgi/trace", timeout=5)
        if 200 <= r.status_code < 400:
            msgs.append("网络连通性：Cloudflare 正常 (1.1.1.1)")
        else:
            r2 = requests.head("https://cloudflare.com", timeout=5, allow_redirects=True)
            if 200 <= r2.status_code < 400:
                msgs.append("网络连通性：Cloudflare 正常 (cloudflare.com)")
            else:
                ok = False
                msgs.append(f"网络连通性：异常（状态 {r.status_code}/{r2.status_code}）")
    except Exception as e:
        ok = False
        msgs.append(f"网络连通性：异常（{e}）")

    # 2) 硅基流动 API Key 有效性
    key = (
        os.getenv("SILICONFLOW_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or conf.get("openai_api_key")
    )
    if not key:
        ok = False
        msgs.append("硅基流动 Key：未设置（SILICONFLOW_API_KEY / OPENAI_API_KEY）")
    else:
        try:
            url = f"{SILICON_BASE}/user/info"
            h = {"Authorization": f"Bearer {key}"}
            resp = requests.get(url, headers=h, timeout=8)
            if resp.status_code == 200:
                info = resp.json() if resp.content else {}
                uid = info.get("id") or info.get("user_id") or "***"
                msgs.append(f"硅基流动 Key：有效（账号 {uid}）")
            elif resp.status_code in {401, 403}:
                ok = False
                msgs.append("硅基流动 Key：无效或无权限（401/403）")
            else:
                ok = False
                msgs.append(f"硅基流动 Key：检测失败（HTTP {resp.status_code}）")
        except Exception as e:
            ok = False
            msgs.append(f"硅基流动 Key：检测异常（{e}）")

    # 3) GDELT API 可访问性（更稳健：先 HEAD 基础地址，再 GET 最小查询；放宽 Content-Type 判定）
    try:
        from urllib.parse import urlencode as _urlencode

        from news2docx.scrape.runner import GDELT_BASE as _GDELT

        # 基础连通性
        try:
            hd = requests.head(_GDELT, timeout=5, allow_redirects=True)
            base_ok = 200 <= hd.status_code < 400
        except Exception:
            base_ok = False

        params = {
            "mode": "ArtList",
            "format": "json",
            "timespan": "1d",
            "sort": "datedesc",
            "query": "domainis:theguardian.com",
            "maxrecords": 1,
        }
        test_url = f"{_GDELT}?{_urlencode(params)}"
        gr = requests.get(test_url, timeout=8)
        if 200 <= gr.status_code < 400:
            # 不强依赖 Content-Type，优先尝试解析 JSON
            parsed = None
            try:
                parsed = gr.json()
            except Exception:
                parsed = None
            if isinstance(parsed, dict) and "articles" in parsed:
                msgs.append("GDELT：可访问（返回JSON）")
            else:
                # 可能是文本/HTML 或空内容，但 HTTP 正常，视为可达
                msgs.append("GDELT：可访问（返回非标准JSON，可能被限流或无数据）")
        elif gr.status_code in {401, 403, 429}:
            # 权限或频率受限，仍视为可达
            msgs.append(f"GDELT：可访问（受限，HTTP {gr.status_code}）")
        else:
            ok = False
            if base_ok:
                msgs.append(f"GDELT：基础可达，但查询失败（HTTP {gr.status_code}）")
            else:
                msgs.append(f"GDELT：不可达（HTTP {gr.status_code}）")
    except Exception as e:
        ok = False
        msgs.append(f"GDELT：检测异常（{e}）")

    # 显示可用免费模型（非关键）
    try:
        ms = free_chat_models()
        msgs.append(f"可用免费模型：{', '.join(ms)}")
    except Exception:
        msgs.append("可用免费模型：获取失败（稍后再试）")

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
        ("openai_api_key", "secret", "翻译服务密钥（必填）"),
        ("processing_word_min", "int", "英文最少字数（过短不翻译）"),
        ("processing_forbidden_prefixes", "list", "过滤前缀（可选，逗号分隔）"),
        ("processing_forbidden_patterns", "list", "过滤规则（正则，可选）"),
        ("export_font_zh_name", "str", "中文字体"),
        ("export_font_zh_size", "float", "中文字号（pt）"),
        ("export_font_en_name", "str", "英文字体"),
        ("export_font_en_size", "float", "英文字号（pt）"),
        ("export_title_bold", "bool", "标题加粗（是/否）"),
    ]

    console.print(
        Panel.fit(
            "配置编辑器：回车保留当前值，输入新值后回车保存该项。\n"
            "提示：翻译服务密钥须前往硅基流动官网申请",
            title="配置",
            style="cyan",
        )
    )
    updated: Dict[str, Any] = dict(conf)

    def _mask_secret(val: Optional[str], show_first: int = 2, show_last: int = 4) -> str:
        s = str(val or "")
        if not s:
            return "(未设置)"
        n = len(s)
        if n <= show_last:
            return "*" * max(0, n - 1) + s[-1]
        head = s[: max(0, show_first)] if n > show_first else ""
        tail = s[-show_last:]
        return f"{head}{'*' * max(0, n - len(head) - len(tail))}{tail}"

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
            prompt_msg = f"{label} [{key}]"
            if typ == "secret":
                # 显示打码后的当前值，回车留空则保持不变
                masked = _mask_secret(str(cur) if cur else None)
                prompt_msg += f"（当前：{masked}；留空不变）"
            new_val = Prompt.ask(prompt_msg, default="" if typ == "secret" else shown)
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
    console.print(Panel.fit(
        "News2Docx — 一键把英文新闻翻译成中文并导出到桌面\n\n"
        "使用说明：\n"
        "1) 系统会自动抓取并挑选10篇英文新闻；\n"
        "2) 自动清洗、分段并翻译为中文；\n"
        "3) 仅导出成功的文章到桌面“英文新闻稿”文件夹；\n"
        "4) 首次使用请先在“设置”里填写翻译服务密钥。\n\n"
        "提示：翻译服务密钥须前往硅基流动官网申请",
        style="cyan",
        title="欢迎",
    ))
    # init logging and load config
    prepare_logging("log.txt")
    conf = load_app_config("config.yml")
    # Mandatory health check at startup
    _doctor(conf)

    while True:
        console.print("选择操作：")
        console.print("  1) 开始处理（自动：抓取→筛选→翻译→导出）")
        console.print("  2) 设置（查看/修改配置）")
        console.print("  3) 体检（检查网络与密钥）")
        console.print("  4) 清除已抓网址缓存")
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
            conf = _config_menu(Path("config.yml"), conf)
        elif choice == "3":
            _doctor(conf)
        elif choice == "4":
            _clear_crawled_cache(conf)
        else:
            console.print("无效选项，请重试。")


if __name__ == "__main__":
    main()
