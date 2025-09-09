from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer

# Reuse existing modules in Phase 1 to keep behavior
import Scraper as scraper_mod
import ai_processor as ai_mod
from news2docx.core.config import load_config_file, load_env, merge_config
from news2docx.core.utils import now_stamp

app = typer.Typer(help="News2Docx CLI (Phase 1) — scrape/process/run")


def _ts() -> str:
    return now_stamp()


def _echo(s: str) -> None:
    typer.echo(s)


@app.command()
def scrape(
    api_token: Optional[str] = typer.Option(None, "--api-token", help="CRAWLER_API_TOKEN"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Crawler API URL"),
    max_urls: Optional[int] = typer.Option(None, "--max-urls", min=1),
    concurrency: Optional[int] = typer.Option(None, "--concurrency", min=1),
    retry_hours: Optional[int] = typer.Option(None, "--retry-hours", min=1),
    timeout: Optional[int] = typer.Option(None, "--timeout", min=5),
    strict_success: Optional[bool] = typer.Option(None, "--strict-success/--no-strict-success"),
    max_api_rounds: Optional[int] = typer.Option(None, "--max-api-rounds", min=1),
    per_url_retries: Optional[int] = typer.Option(None, "--per-url-retries", min=0),
    pick_mode: Optional[str] = typer.Option(None, "--pick-mode", case_sensitive=False),
    random_seed: Optional[int] = typer.Option(None, "--random-seed"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """抓取新闻并将结果保存为JSON文件。"""
    conf = merge_config(
        load_config_file(config),
        load_env(),
        {
            "crawler_api_token": api_token,
            "crawler_api_url": api_url,
            "max_urls": max_urls,
            "concurrency": concurrency,
            "retry_hours": retry_hours,
            "timeout": timeout,
            "strict_success": strict_success,
            "max_api_rounds": max_api_rounds,
            "per_url_retries": per_url_retries,
            "pick_mode": pick_mode,
            "random_seed": random_seed,
        },
    )

    token = conf.get("crawler_api_token") or os.getenv("CRAWLER_API_TOKEN")
    if not token:
        typer.secho("缺少 CRAWLER_API_TOKEN，请使用 --api-token 或设置环境变量。", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    cfg = scraper_mod.ScrapeConfig(
        output_dir="",
        api_url=conf.get("crawler_api_url") or scraper_mod.DEFAULT_CRAWLER_API_URL,
        api_token=token,
        max_urls=int(conf.get("max_urls") or 1),
        concurrency=int(conf.get("concurrency") or 4),
        retry_interval_hours=int(conf.get("retry_hours") or 24),
        request_timeout=int(conf.get("timeout") or 30),
        strict_success=bool(conf.get("strict_success") if conf.get("strict_success") is not None else True),
        max_api_rounds=int(conf.get("max_api_rounds") or 5),
        per_url_retries=int(conf.get("per_url_retries") or 2),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=conf.get("random_seed"),
    )

    ns = scraper_mod.NewsScraper(cfg)
    results = ns.run()
    _echo(f"抓取完成：成功 {results.success}，失败 {results.failed}")

    if results.success > 0:
        ts = _ts()
        path = scraper_mod.save_scraped_data_to_json(results, ts)
        _echo(f"已保存抓取结果：{path}")


@app.command()
def process(
    input_json: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    target_language: Optional[str] = typer.Option(None, "--target-language", help="目标语言"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """处理抓取JSON，调用AI两步法并输出处理后的JSON。"""
    with input_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    articles_raw = data.get("articles", [])
    articles: list[ai_mod.Article] = []
    for a in articles_raw:
        try:
            idx = int(a.get("id") or a.get("index") or 0)
        except Exception:
            idx = 0
        art = ai_mod.Article(
            index=idx,
            url=a.get("url", ""),
            title=a.get("title", ""),
            content=a.get("content", ""),
            content_length=int(a.get("content_length", 0) or 0),
            word_count=int(a.get("words", 0) or a.get("word_count", 0) or 0),
        )
        articles.append(art)

    if not articles:
        typer.secho("输入中无文章可处理。", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    conf = merge_config(load_config_file(config), load_env(), {"target_language": target_language})
    result = ai_mod.process_articles_two_steps_concurrent(articles, target_lang=conf.get("target_language") or "Chinese")

    ts = _ts()
    out_path = Path(f"processed_news_{ts}.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _echo(f"已保存处理结果：{out_path}")


@app.command()
def run(
    api_token: Optional[str] = typer.Option(None, "--api-token", help="CRAWLER_API_TOKEN"),
    api_url: Optional[str] = typer.Option(None, "--api-url", help="Crawler API URL"),
    max_urls: Optional[int] = typer.Option(None, "--max-urls", min=1),
    concurrency: Optional[int] = typer.Option(None, "--concurrency", min=1),
    retry_hours: Optional[int] = typer.Option(None, "--retry-hours", min=1),
    timeout: Optional[int] = typer.Option(None, "--timeout", min=5),
    strict_success: Optional[bool] = typer.Option(None, "--strict-success/--no-strict-success"),
    max_api_rounds: Optional[int] = typer.Option(None, "--max-api-rounds", min=1),
    per_url_retries: Optional[int] = typer.Option(None, "--per-url-retries", min=0),
    pick_mode: Optional[str] = typer.Option(None, "--pick-mode", case_sensitive=False),
    random_seed: Optional[int] = typer.Option(None, "--random-seed"),
    target_language: Optional[str] = typer.Option(None, "--target-language"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """端到端：抓取 → AI两步处理。Phase 1 暂不导出DOCX。"""
    conf = merge_config(
        load_config_file(config),
        load_env(),
        {
            "crawler_api_token": api_token,
            "crawler_api_url": api_url,
            "max_urls": max_urls,
            "concurrency": concurrency,
            "retry_hours": retry_hours,
            "timeout": timeout,
            "strict_success": strict_success,
            "max_api_rounds": max_api_rounds,
            "per_url_retries": per_url_retries,
            "pick_mode": pick_mode,
            "random_seed": random_seed,
            "target_language": target_language,
        },
    )

    token = conf.get("crawler_api_token") or os.getenv("CRAWLER_API_TOKEN")
    if not token:
        typer.secho("缺少 CRAWLER_API_TOKEN，请使用 --api-token 或设置环境变量。", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    cfg = scraper_mod.ScrapeConfig(
        output_dir="",
        api_url=conf.get("crawler_api_url") or scraper_mod.DEFAULT_CRAWLER_API_URL,
        api_token=token,
        max_urls=int(conf.get("max_urls") or 1),
        concurrency=int(conf.get("concurrency") or 4),
        retry_interval_hours=int(conf.get("retry_hours") or 24),
        request_timeout=int(conf.get("timeout") or 30),
        strict_success=bool(conf.get("strict_success") if conf.get("strict_success") is not None else True),
        max_api_rounds=int(conf.get("max_api_rounds") or 5),
        per_url_retries=int(conf.get("per_url_retries") or 2),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=conf.get("random_seed"),
    )

    ns = scraper_mod.NewsScraper(cfg)
    results = ns.run()
    _echo(f"抓取完成：成功 {results.success}，失败 {results.failed}")

    if results.success <= 0:
        typer.secho("无可处理文章，结束。", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    scraped_ts = _ts()
    scraped_path = scraper_mod.save_scraped_data_to_json(results, scraped_ts)
    _echo(f"已保存抓取结果：{scraped_path}")

    # 直接基于内存中的 articles 处理
    processed = ai_mod.process_articles_two_steps_concurrent(
        results.articles, target_lang=conf.get("target_language") or "Chinese"
    )
    proc_ts = _ts()
    processed_path = Path(f"processed_news_{proc_ts}.json")
    processed_path.write_text(json.dumps(processed, ensure_ascii=False, indent=2), encoding="utf-8")
    _echo(f"已保存处理结果：{processed_path}")


@app.command()
def export(
    processed_json: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 DOCX 路径，可省略自动命名"),
    order: Optional[str] = typer.Option(None, "--order", help="段落输出顺序：zh-en 或 en-zh"),
    mono: Optional[bool] = typer.Option(None, "--mono", help="仅中文输出，不含英文"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """根据处理结果导出 DOCX 文档。"""
    from news2docx.export.docx import DocumentWriter, DocumentConfig

    data = json.loads(processed_json.read_text(encoding="utf-8"))
    ts = _ts()
    conf = merge_config(load_config_file(config), load_env(), {
        "export_order": (order.lower() if isinstance(order, str) else order),
        "export_mono": mono,
    })
    out_path = output or Path(f"news_{ts}.docx")

    cfg = DocumentConfig(
        bilingual=not bool(conf.get("export_mono") or False),
        order=str(conf.get("export_order") or "zh-en").lower(),
    )
    writer = DocumentWriter(cfg)
    writer.write_from_processed(data, str(out_path))
    _echo(f"导出完成：{out_path}")


@app.command()
def doctor() -> None:
    """检查必要环境变量与端点连通性（不会发起真实业务调用）。"""
    import requests

    ok = True
    sf_key = os.getenv("SILICONFLOW_API_KEY")
    crawler_token = os.getenv("CRAWLER_API_TOKEN")
    crawler_url = os.getenv("CRAWLER_API_URL") or "https://gdelt-xupojkickl.cn-hongkong.fcapp.run"
    sf_url = os.getenv("SILICONFLOW_URL") or "https://api.siliconflow.cn/v1/chat/completions"

    if not crawler_token:
        ok = False
        typer.secho("未设置 CRAWLER_API_TOKEN", fg=typer.colors.YELLOW)
    if not sf_key:
        ok = False
        typer.secho("未设置 SILICONFLOW_API_KEY", fg=typer.colors.YELLOW)

    # 端点连通性（宽松判定：只要能返回响应，不论状态码，即视为可达）
    try:
        r = requests.get(crawler_url, timeout=5)
        typer.echo(f"Crawler 可达: {r.status_code}")
    except Exception as e:
        ok = False
        typer.secho(f"Crawler 不可达: {e}", fg=typer.colors.RED)

    try:
        # 大多数会 405/404，但只要没有网络错误即可
        r2 = requests.get(sf_url, timeout=5)
        typer.echo(f"SiliconFlow 可达: {r2.status_code}")
    except Exception as e:
        ok = False
        typer.secho(f"SiliconFlow 不可达: {e}", fg=typer.colors.RED)

    if ok:
        typer.secho("健康检查通过。", fg=typer.colors.GREEN)
    else:
        typer.secho("健康检查发现问题，请根据提示修复。", fg=typer.colors.RED)


def main() -> None:  # console_scripts entrypoint wrapper
    app()


if __name__ == "__main__":
    main()
