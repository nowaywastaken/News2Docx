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
from news2docx.process.engine import process_articles_two_steps_concurrent
from news2docx.core.config import load_config_file, load_env, merge_config
from news2docx.core.utils import now_stamp, ensure_directory


app = typer.Typer(help="News2Docx CLI: scrape, process, run, export")


def _ts() -> str:
    return now_stamp()


def _echo(s: str) -> None:
    typer.echo(s)


def _desktop_outdir() -> Path:
    home = Path.home()
    desktop = home / "Desktop"
    # Use the required Chinese folder name without embedding Chinese characters in source
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"  # "英文新闻稿"
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
        typer.secho("Missing CRAWLER_API_TOKEN. Use --api-token or set env.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    cfg = ScrapeConfig(
        api_url=conf.get("crawler_api_url") or DEFAULT_CRAWLER_API_URL,
        api_token=token,
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

    articles_raw = data.get("articles", [])
    articles: list[ProcArticle] = []
    for a in articles_raw:
        try:
            idx = int(a.get("id") or a.get("index") or 0)
        except Exception:
            idx = 0
        art = ProcArticle(
            index=idx,
            url=a.get("url", ""),
            title=a.get("title", ""),
            content=a.get("content", ""),
            content_length=int(a.get("content_length", 0) or 0),
            word_count=int(a.get("words", 0) or a.get("word_count", 0) or 0),
        )
        articles.append(art)

    if not articles:
        typer.secho("No articles to process in input.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    conf = merge_config(load_config_file(config), load_env(), {"target_language": target_language})
    # Ensure engine can read API key from env if provided in config
    if conf.get("siliconflow_api_key") and not os.getenv("SILICONFLOW_API_KEY"):
        os.environ["SILICONFLOW_API_KEY"] = str(conf.get("siliconflow_api_key"))
    merge_short = conf.get("merge_short_paragraph_chars")
    try:
        merge_short = int(merge_short) if merge_short is not None else None
    except Exception:
        merge_short = None
    result = process_articles_two_steps_concurrent(articles, target_lang=conf.get("target_language") or "Chinese", merge_short_chars=merge_short)

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
    # Ensure engine can read API key from env if provided in config
    if conf.get("siliconflow_api_key") and not os.getenv("SILICONFLOW_API_KEY"):
        os.environ["SILICONFLOW_API_KEY"] = str(conf.get("siliconflow_api_key"))

    token = conf.get("crawler_api_token") or os.getenv("CRAWLER_API_TOKEN")
    if not token:
        typer.secho("Missing CRAWLER_API_TOKEN. Use --api-token or set env.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    run_id = _ts()
    run_dir = ensure_directory(Path("runs") / run_id)

    cfg = ScrapeConfig(
        api_url=conf.get("crawler_api_url") or DEFAULT_CRAWLER_API_URL,
        api_token=token,
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
    arts: list[ProcArticle] = []
    for a in results.articles:
        try:
            idx = int(getattr(a, "index", 0) or 0)
        except Exception:
            idx = 0
        arts.append(
            ProcArticle(
                index=idx,
                url=getattr(a, "url", ""),
                title=getattr(a, "title", ""),
                content=getattr(a, "content", ""),
                content_length=int(getattr(a, "content_length", 0) or 0),
                word_count=int(getattr(a, "word_count", 0) or 0),
            )
        )
    merge_short = conf.get('merge_short_paragraph_chars')
    try:
        merge_short = int(merge_short) if merge_short is not None else None
    except Exception:
        merge_short = None
    processed = process_articles_two_steps_concurrent(arts, target_lang=conf.get("target_language") or "Chinese", merge_short_chars=merge_short)
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
        from news2docx.export.docx import DocumentWriter, DocumentConfig

        export_conf = merge_config(
            load_config_file(config),
            load_env(),
            {
                "export_order": (order.lower() if isinstance(order, str) else order),
                "export_mono": mono,
            },
        )
        desktop_dir = _desktop_outdir()
        out_dir_cfg = export_conf.get("export_out_dir")
        export_dir = Path(str(out_dir_cfg)) if out_dir_cfg else desktop_dir
        from news2docx.export.docx import FontConfig as _FontCfg
        cfg_doc = DocumentConfig(
            bilingual=not bool(export_conf.get("export_mono") or False),
            order=str(export_conf.get("export_order") or "zh-en").lower(),
            first_line_indent_cm=float(export_conf.get("export_first_line_indent_cm") or 0.74),
            font_zh=_FontCfg(name=str(export_conf.get("export_font_zh_name") or 'SimSun'), size_pt=float(export_conf.get("export_font_zh_size") or 10.5)),
            font_en=_FontCfg(name=str(export_conf.get("export_font_en_name") or 'Cambria'), size_pt=float(export_conf.get("export_font_en_size") or 10.5)),
            title_size_multiplier=float(export_conf.get("export_title_size_multiplier") or 1.0),
            title_bold=bool(export_conf.get("export_title_bold") if export_conf.get("export_title_bold") is not None else True),
        )
        out_path = (export_dir / (output.name if (output and output.suffix.lower()=='.docx') else f"news_{run_id}.docx")) if output else (export_dir / f"news_{run_id}.docx")
        writer = DocumentWriter(cfg_doc)
        data = json.loads(processed_path.read_text(encoding="utf-8"))
        if split_flag:
            # Use configured output directory (or Desktop)
            out_dir = str(export_dir)
            paths = writer.write_per_article(data, out_dir)
            _echo(f"Exported {len(paths)} DOCX files")
        else:
            writer.write_from_processed(data, str(out_path))
            _echo(f"Exported DOCX: {out_path}")


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
    from news2docx.export.docx import DocumentWriter, DocumentConfig

    if processed_json is None:
        runs = sorted((Path("runs").glob("*/processed.json")), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runs:
            typer.secho("No runs/*/processed.json found; please provide a path.", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        processed_json = runs[0]
    data = json.loads(processed_json.read_text(encoding="utf-8"))
    ts = _ts()
    conf = merge_config(load_config_file(config), load_env(), {
        "export_order": (order.lower() if isinstance(order, str) else order),
        "export_mono": mono,
    })
    desktop_dir = _desktop_outdir()
    out_dir_cfg = conf.get("export_out_dir")
    export_dir = Path(str(out_dir_cfg)) if out_dir_cfg else desktop_dir
    out_path = (export_dir / (output.name if (output and output.suffix.lower()=='.docx') else f"news_{ts}.docx")) if output else (export_dir / f"news_{ts}.docx")

    cfg_doc = DocumentConfig(
        bilingual=not bool(conf.get("export_mono") or False),
        order=str(conf.get("export_order") or "zh-en").lower(),
    )
    writer = DocumentWriter(cfg_doc)
    split_flag = split if split is not None else bool(
        conf.get("export_split") if conf.get("export_split") is not None else True
    )
    if split_flag:
        out_dir = str(export_dir)
        paths = writer.write_per_article(data, out_dir)
        _echo(f"Exported {len(paths)} DOCX files")
    else:
        writer.write_from_processed(data, str(out_path))
        _echo(f"Exported DOCX: {out_path}")


@app.command()
def doctor(
    config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, readable=True)
) -> None:
    """Check required env vars and endpoint reachability (no real calls)."""
    import requests

    ok = True
    conf = merge_config(load_config_file(config), load_env())
    # propagate API key from config to env if needed
    if conf.get("siliconflow_api_key") and not os.getenv("SILICONFLOW_API_KEY"):
        os.environ["SILICONFLOW_API_KEY"] = str(conf.get("siliconflow_api_key"))

    sf_key = os.getenv("SILICONFLOW_API_KEY")
    crawler_token = os.getenv("CRAWLER_API_TOKEN") or str(conf.get("crawler_api_token") or "")
    crawler_url = os.getenv("CRAWLER_API_URL") or str(conf.get("crawler_api_url") or "https://gdelt-xupojkickl.cn-hongkong.fcapp.run")
    sf_url = os.getenv("SILICONFLOW_URL") or "https://api.siliconflow.cn/v1/chat/completions"

    if not crawler_token:
        ok = False
        typer.secho("CRAWLER_API_TOKEN is not set (env or config)", fg=typer.colors.YELLOW)
    if not sf_key:
        ok = False
        typer.secho("SILICONFLOW_API_KEY is not set (env or config)", fg=typer.colors.YELLOW)

    # Reachability: any HTTP response (even 4xx/5xx) counts as reachable
    try:
        r = requests.get(crawler_url, timeout=5)
        typer.echo(f"Crawler reachable: {r.status_code}")
    except Exception as e:
        ok = False
        typer.secho(f"Crawler unreachable: {e}", fg=typer.colors.RED)

    try:
        # Likely 405/404, but network OK means reachable
        r2 = requests.get(sf_url, timeout=5)
        typer.echo(f"SiliconFlow reachable: {r2.status_code}")
    except Exception as e:
        ok = False
        typer.secho(f"SiliconFlow unreachable: {e}", fg=typer.colors.RED)

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
    runs_dir = Path("runs")
    if not runs_dir.exists():
        typer.echo("runs directory not found")
        return
    runs = sorted(runs_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest = runs[0].name if runs else "N/A"
    typer.echo(f"runs: {len(runs)} | latest: {latest}")


@app.command()
def clean(keep: int = typer.Option(3, '--keep', min=0, help='Keep the latest N runs/* directories')) -> None:
    """Remove old runs directories, keeping the most recent N."""
    runs = sorted(Path('runs').glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in runs[keep:]:
        try:
            for f in p.glob('*'):
                f.unlink(missing_ok=True)
            p.rmdir()
            typer.echo(f"Deleted {p}")
        except Exception as e:
            typer.secho(f"Unable to delete {p}: {e}", fg=typer.colors.YELLOW)


@app.command()
def resume(
    target_language: Optional[str] = typer.Option(None, '--target-language'),
    config: Optional[Path] = typer.Option(None, '--config', exists=True, dir_okay=False, readable=True),
) -> None:
    """Resume from latest runs/<run_id>: if processed.json is missing, process scraped.json to generate it."""
    runs = sorted(Path('runs').glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        typer.secho('No runs/* directories found', fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)
    latest = runs[0]
    scraped_path = latest / 'scraped.json'
    processed = latest / 'processed.json'
    if processed.exists():
        typer.echo(f"Already exists: {processed}")
        raise typer.Exit(code=0)
    conf = merge_config(load_config_file(config), load_env(), {"target_language": target_language})
    data = json.loads(scraped_path.read_text(encoding='utf-8'))
    arts: list[ProcArticle] = []
    for a in data.get('articles', []):
        try:
            idx = int(a.get('id') or a.get('index') or 0)
        except Exception:
            idx = 0
        arts.append(ProcArticle(
            index=idx,
            url=a.get('url',''),
            title=a.get('title',''),
            content=a.get('content',''),
            content_length=int(a.get('content_length',0) or 0),
            word_count=int(a.get('words',0) or a.get('word_count',0) or 0),
        ))
    merge_short = conf.get('merge_short_paragraph_chars')
    try:
        merge_short = int(merge_short) if merge_short is not None else None
    except Exception:
        merge_short = None
    res = process_articles_two_steps_concurrent(arts, target_lang=conf.get('target_language') or 'Chinese', merge_short_chars=merge_short)
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
