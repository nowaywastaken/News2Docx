from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer

from news2docx.scrape.runner import (
    ScrapeConfig as ScrapeConfig,
    NewsScraper as NewsScraper,
    DEFAULT_CRAWLER_API_URL,
    save_scraped_data_to_json,
)
from news2docx.process.engine import Article as ProcArticle
from news2docx.core.config import load_config_file, load_env, merge_config
from news2docx.core.utils import now_stamp, ensure_directory
from news2docx.cli.common import ensure_openai_env
from news2docx.services.processing import (
    articles_from_json,
    articles_from_scraped,
    process_articles as svc_process_articles,
)
from news2docx.services.runs import runs_base_dir, latest_run_dir, clean_runs as svc_clean_runs


app = typer.Typer(help="News2Docx CLI: scrape, process, run, export")


def _ts() -> str:
    return now_stamp()


def _echo(s: str) -> None:
    typer.echo(s)


def _desktop_outdir() -> Path:
    home = Path.home()
    desktop = home / "Desktop"
    # Use the required Chinese folder name without embedding Chinese characters in source
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"  # "鑻辨枃鏂伴椈绋?
    outdir = desktop / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


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
    """Scrape news URLs and save results to a JSON file."""
    conf = merge_config(
        load_config_file(config),
        load_env(),
        {
            "crawler_api_token": api_token,
            "crawler_api_url": api_url,
            "crawler_mode": None,  # from config/env when provided
            "crawler_sites_file": None,
            "max_urls": max_urls,
            "concurrency": concurrency,
            "retry_hours": retry_hours,
            "timeout": timeout,
            "strict_success": strict_success,
            "max_api_rounds": max_api_rounds,
            "per_url_retries": per_url_retries,
            "pick_mode": pick_mode,
            "random_seed": random_seed,
            "gdelt_timespan": None,
            "gdelt_max_per_call": None,
            "gdelt_sort": None,
        },
    )

    mode = str(conf.get("crawler_mode") or os.getenv("CRAWLER_MODE") or "remote").lower()
    token = conf.get("crawler_api_token") or os.getenv("CRAWLER_API_TOKEN")
    if mode == "remote" and not token:
        typer.secho("Missing CRAWLER_API_TOKEN (remote mode). Use --api-token or set env, or switch to local mode.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    cfg = ScrapeConfig(
        api_url=conf.get("crawler_api_url") or DEFAULT_CRAWLER_API_URL,
        api_token=token,
        mode=mode,
        sites_file=(conf.get("crawler_sites_file") or os.getenv("CRAWLER_SITES_FILE") or str(Path.cwd() / "server" / "news_website.txt")),
        gdelt_timespan=(conf.get("gdelt_timespan") or os.getenv("GDELT_TIMESPAN") or "7d"),
        gdelt_max_per_call=int(conf.get("gdelt_max_per_call") or os.getenv("GDELT_MAX_PER_CALL") or 50),
        gdelt_sort=(conf.get("gdelt_sort") or os.getenv("GDELT_SORT") or "datedesc"),
        max_urls=int(conf.get("max_urls") or 1),
        concurrency=int(conf.get("concurrency") or 4),
        timeout=int(conf.get("timeout") or 30),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=(int(conf.get("random_seed")) if conf.get("random_seed") is not None else None),
        db_path=str(conf.get("db_path") or os.getenv("N2D_DB_PATH") or (Path.cwd() / ".n2d_cache" / "crawled.sqlite3")),
        noise_patterns=(conf.get("noise_patterns") if isinstance(conf.get("noise_patterns"), list) else None),
    )

    ns = NewsScraper(cfg)
    results = ns.run()
    _echo(f"Scrape done: success {results.success}, failed {results.failed}")

    if results.success > 0:
        ts = _ts()
        path = save_scraped_data_to_json(results, ts)
        _echo(f"Saved scraped JSON: {path}")


@app.command()
def process(
    input_json: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    target_language: Optional[str] = typer.Option(None, "--target-language", help="Target language"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """Process scraped JSON using a two-step AI pipeline and output JSON."""
    with input_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    articles: list[ProcArticle] = articles_from_json(data)

    if not articles:
        typer.secho("No articles to process in input.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    conf = merge_config(load_config_file(config), load_env(), {"target_language": target_language})
    ensure_openai_env(conf)
    result = svc_process_articles(articles, conf)

    ts = _ts()
    out_path = Path(f"processed_news_{ts}.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _echo(f"Saved processed JSON: {out_path}")


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
    target_language: Optional[str] = typer.Option(None, "--target-language", help="Target language"),
    export_docx: Optional[bool] = typer.Option(None, "--export/--no-export", help="Export DOCX after processing (can be set via config: run_export)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="DOCX output file (single) or directory when splitting"),
    order: Optional[str] = typer.Option(None, "--order", help="Paragraph order: zh-en or en-zh (with --export)"),
    mono: Optional[bool] = typer.Option(None, "--mono", help="Chinese only (with --export)"),
    split: Optional[bool] = typer.Option(None, "--split/--no-split", help="Export one DOCX per article (can be set via config: export_split; defaults to True)"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """End-to-end: scrape and two-step AI processing; optional DOCX export."""
    conf = merge_config(
        load_config_file(config),
        load_env(),
        {
            "crawler_api_token": api_token,
            "crawler_api_url": api_url,
            "crawler_mode": None,
            "crawler_sites_file": None,
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
            "gdelt_timespan": None,
            "gdelt_max_per_call": None,
            "gdelt_sort": None,
        },
    )
    # Ensure engine can read API key from env if provided in config
    ensure_openai_env(conf)

    mode = str(conf.get("crawler_mode") or os.getenv("CRAWLER_MODE") or "remote").lower()
    token = conf.get("crawler_api_token") or os.getenv("CRAWLER_API_TOKEN")
    if mode == "remote" and not token:
        typer.secho("Missing CRAWLER_API_TOKEN (remote mode). Use --api-token or set env, or switch to local mode.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    run_id = _ts()
    run_dir = ensure_directory(runs_base_dir(conf) / run_id)

    cfg = ScrapeConfig(
        api_url=conf.get("crawler_api_url") or DEFAULT_CRAWLER_API_URL,
        api_token=token,
        mode=mode,
        sites_file=(conf.get("crawler_sites_file") or os.getenv("CRAWLER_SITES_FILE") or str(Path.cwd() / "server" / "news_website.txt")),
        gdelt_timespan=(conf.get("gdelt_timespan") or os.getenv("GDELT_TIMESPAN") or "7d"),
        gdelt_max_per_call=int(conf.get("gdelt_max_per_call") or os.getenv("GDELT_MAX_PER_CALL") or 50),
        gdelt_sort=(conf.get("gdelt_sort") or os.getenv("GDELT_SORT") or "datedesc"),
        max_urls=int(conf.get("max_urls") or 1),
        concurrency=int(conf.get("concurrency") or 4),
        timeout=int(conf.get("timeout") or 30),
        pick_mode=str(conf.get("pick_mode") or "random"),
        random_seed=(int(conf.get("random_seed")) if conf.get("random_seed") is not None else None),
        db_path=str(conf.get("db_path") or os.getenv("N2D_DB_PATH") or (Path.cwd() / ".n2d_cache" / "crawled.sqlite3")),
        noise_patterns=(conf.get("noise_patterns") if isinstance(conf.get("noise_patterns"), list) else None),
    )

    ns = NewsScraper(cfg)
    results = ns.run()
    _echo(f"Scrape done: success {results.success}, failed {results.failed}")

    if results.success <= 0:
        typer.secho("No articles to process; exiting.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    scraped_path = run_dir / "scraped.json"
    save_path = save_scraped_data_to_json(results, run_id)
    try:
        Path(save_path).replace(scraped_path)
    except Exception:
        scraped_path.write_text(Path(save_path).read_text(encoding="utf-8"), encoding="utf-8")
    _echo(f"Saved scraped JSON: {scraped_path}")

    # Convert scraped Article (scrape.runner) -> engine Article
    arts: list[ProcArticle] = articles_from_scraped(results.articles)
    processed = svc_process_articles(arts, conf)
    processed_path = run_dir / "processed.json"
    processed_path.write_text(json.dumps(processed, ensure_ascii=False, indent=2), encoding="utf-8")
    _echo(f"Saved processed JSON: {processed_path}")

    # Determine export and split flags from CLI or config
    export_flag = export_docx if export_docx is not None else bool(
        conf.get("run_export") or conf.get("export_auto") or conf.get("export")
    )
    split_flag = split if split is not None else bool(
        conf.get("export_split") if conf.get("export_split") is not None else True
    )

    if export_flag:
        export_conf = merge_config(
            load_config_file(config),
            load_env(),
            {"export_order": (order.lower() if isinstance(order, str) else order), "export_mono": mono},
        )
        from news2docx.services.exporting import export_processed
        res = export_processed(
            processed_path,
            export_conf,
            output=output,
            split=split_flag,
            default_filename=f"news_{run_id}.docx",
        )
        if res.get("split"):
            _echo(f"Exported {len(res.get('paths', []))} DOCX files")
        else:
            _echo(f"Exported DOCX: {res.get('path')}")


@app.command()
def export(
    processed_json: Optional[Path] = typer.Argument(None, exists=True, dir_okay=False, readable=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="DOCX output file (single) or directory when splitting"),
    order: Optional[str] = typer.Option(None, "--order", help="Paragraph order: zh-en or en-zh"),
    mono: Optional[bool] = typer.Option(None, "--mono", help="Chinese only, no English"),
    split: Optional[bool] = typer.Option(None, "--split/--no-split", help="Export one DOCX per article (can be set via config: export_split; defaults to True)"),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True),
) -> None:
    """Export a DOCX document from processed JSON."""
    if processed_json is None:
        base_dir = runs_base_dir()
        runs = sorted((base_dir.glob("*/processed.json")), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            typer.secho("No runs/*/processed.json found; please provide a path.", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        processed_json = runs[0]
    ts = _ts()
    conf = merge_config(load_config_file(config), load_env(), {
        "export_order": (order.lower() if isinstance(order, str) else order),
        "export_mono": mono,
    })
    from news2docx.services.exporting import export_processed
    res = export_processed(
        processed_json,
        conf,
        output=output,
        split=split,
        default_filename=f"news_{ts}.docx",
    )
    if res.get("split"):
        _echo(f"Exported {len(res.get('paths', []))} DOCX files")
    else:
        _echo(f"Exported DOCX: {res.get('path')}")


@app.command()
def doctor(
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True)
) -> None:
    """Check required env vars and endpoint reachability (no real calls)."""
    import requests

    ok = True
    conf = merge_config(load_config_file(config), load_env())
    # propagate API key/base from config to env if needed
    ensure_openai_env(conf)

    oa_key = os.getenv("OPENAI_API_KEY")
    mode = str(conf.get("crawler_mode") or os.getenv("CRAWLER_MODE") or "remote").lower()
    crawler_token = os.getenv("CRAWLER_API_TOKEN") or str(conf.get("crawler_api_token") or "")
    crawler_url = os.getenv("CRAWLER_API_URL") or str(conf.get("crawler_api_url") or "https://gdelt-xupojkickl.cn-hongkong.fcapp.run")
    # Determine OpenAI-Compatible chat completions URL
    base = os.getenv("OPENAI_API_BASE") or str(conf.get("openai_api_base") or "https://api.siliconflow.cn/v1")
    full_url_override = os.getenv("OPENAI_API_URL")
    chat_url = full_url_override or (base.rstrip("/") + "/chat/completions")

    if mode == "remote" and not crawler_token:
        ok = False
        typer.secho("CRAWLER_API_TOKEN is not set (env or config, remote mode)", fg=typer.colors.YELLOW)
    if not oa_key:
        ok = False
        typer.secho("OPENAI_API_KEY is not set (env or config)", fg=typer.colors.YELLOW)

    # Reachability: any HTTP response (even 4xx/5xx) counts as reachable
    if mode == "remote":
        try:
            r = requests.get(crawler_url, timeout=5)
            typer.echo(f"Crawler reachable: {r.status_code}")
        except Exception as e:
            ok = False
            typer.secho(f"Crawler unreachable: {e}", fg=typer.colors.RED)
    else:
        typer.echo("Crawler mode: local (will call GDELT directly at runtime)")

    try:
        # Likely 405/404, but network OK means reachable
        r2 = requests.get(chat_url, timeout=5)
        typer.echo(f"OpenAI-Compatible chat endpoint reachable: {r2.status_code}")
    except Exception as e:
        ok = False
        typer.secho(f"OpenAI-Compatible endpoint unreachable: {e}", fg=typer.colors.RED)

    # Show export target directory
    try:
        outdir = _desktop_outdir()
        typer.echo(f"Export directory: {outdir}")
    except Exception as e:
        typer.secho(f"Cannot prepare export outdir: {e}", fg=typer.colors.YELLOW)

    if ok:
        typer.secho("Health check passed", fg=typer.colors.GREEN)
    else:
        typer.secho("Health check failed; see messages above", fg=typer.colors.RED)


@app.command()
def stats() -> None:
    """Show number of runs and latest run id."""
    runs_dir = runs_base_dir()
    if not runs_dir.exists():
        typer.echo("runs directory not found")
        return
    runs = sorted(runs_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest = runs[0].name if runs else "N/A"
    typer.echo(f"runs: {len(runs)} | latest: {latest}")


@app.command()
def clean(keep: int = typer.Option(3, '--keep', min=0, help='Keep the latest N runs/* directories')) -> None:
    """Remove old runs directories, keeping the most recent N."""
    base = runs_base_dir()
    deleted = svc_clean_runs(base, keep)
    for p in deleted:
        typer.echo(f"Deleted {p}")


@app.command()
def resume(
    target_language: Optional[str] = typer.Option(None, '--target-language'),
    config: Optional[Path] = typer.Option(None, '--config', exists=True, dir_okay=False, readable=True),
) -> None:
    """Resume from latest runs/<run_id>: if processed.json is missing, process scraped.json to generate it."""
    base = runs_base_dir()
    latest = latest_run_dir(base)
    if not latest:
        typer.secho('No runs/* directories found', fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)
    scraped_path = latest / 'scraped.json'
    processed = latest / 'processed.json'
    if processed.exists():
        typer.echo(f"Already exists: {processed}")
        raise typer.Exit(code=0)
    conf = merge_config(load_config_file(config), load_env(), {"target_language": target_language})
    data = json.loads(scraped_path.read_text(encoding='utf-8'))
    arts = articles_from_json(data)
    res = svc_process_articles(arts, conf)
    processed.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    typer.echo(f"Resume processing done: {processed}")


@app.command()
def combine(
    inputs: list[Path] = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Optional[Path] = typer.Option(None, '--output', '-o'),
) -> None:
    """Combine multiple processed_news_*.json files into one."""
    merged = {"articles": [], "metadata": {"combined": len(inputs)}}
    for p in inputs:
        d = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(d, dict) and 'articles' in d:
            merged['articles'].extend(d['articles'])
    out = output or Path(f"processed_combined_{_ts()}.json")
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    typer.echo(f"Combined into: {out}")


def main() -> None:  # console_scripts entrypoint wrapper
    app()


if __name__ == "__main__":
    main()


