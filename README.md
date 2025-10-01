# News2Docx

轻量、可配置的英文新闻到 DOCX 工具：抓 URL、并发抓正文、AI 控字与翻译、导出规范排版文档。

![python](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

English summary: Fetch English news, condense to target length, translate to Chinese, and export nicely formatted DOCX via a simple CLI.

## Features

- 简洁：单命令端到端，或按阶段拆分运行。
- 可选抓取模式：remote（默认，国内网络友好）/ local（直连 GDELT）。
- 并发与去噪：内置站点选择器 + 噪声过滤，支持覆盖自定义选择器。
- 两步 AI 流程：字数调整 400–450 词 + 精准段落对齐翻译（OpenAI-Compatible）。
- DOCX 导出：标题居中、首行缩进、可配中英字体；合并导出或按篇拆分。
- 可移植：Windows/macOS/Linux；配置文件与环境变量双通道。

## Requirements

- Python 3.11+
- 可访问外网（抓取端点与 LLM 接口）

## Install

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可选冒烟（不联网，仅验证导出链路）：

```bash
python scripts/smoke.py
```

## Quick Start

1) 编辑配置 `config.yml`，至少填入：

- `crawler_api_url`（remote 模式）与 `crawler_api_token`
- `openai_api_key`（OpenAI-Compatible，必填）

2) 端到端运行：

```bash
python -m news2docx.cli.main run --config config.yml
```

3) 分阶段：

```bash
# 仅抓取：保存 scraped_news_*.json
python -m news2docx.cli.main scrape --config config.yml --max-urls 3

# 仅处理：输入上一步 JSON，输出 processed_news_*.json
python -m news2docx.cli.main process scraped_news_20240101_120000.json --config config.yml

# 仅导出：默认选取最新 runs/*/processed.json
python -m news2docx.cli.main export --config config.yml --split/--no-split
```

## UI（PyQt）

- 启动：`python index.py`（无需参数，自动读取根目录 `config.yml`）
- 窗口：固定 `350x600`，启用高 DPI；仅使用 Absolute Positioning、`QFormLayout`、`QStackedLayout`
- 页面：
  - 主页：应用信息 + 实时日志（根目录 `log.txt`）
  - 设置：关键配置只读展示（抓取/处理/导出）
- 操作按钮：一键运行、抓取、处理、导出；日志同时输出到终端与 `log.txt`

函数说明（index.py）：
- `load_app_config(config_path)`：加载配置（严格读取指定路径）。
- `prepare_logging(log_file)`：初始化日志到单一文件并同步输出到控制台。
- `run_scrape(conf)`：执行抓取，保存 `scraped_news_*.json`。
- `run_process(conf, scraped_json_path)`：两步处理，写入 `runs/<id>/processed.json`。
- `run_export(conf, processed_json_path)`：按配置导出 DOCX（单文件或分篇）。
- `run_app()`：高 DPI 初始化、加载配置与日志、启动主窗口。

UI 相关配置示例：

```yaml
app:
  name: "News2Docx UI"
ui:
  fixed_width: 350
  fixed_height: 600
  high_dpi: true
  initial_page: 0
  theme:
    primary_color: "#4C7DFF"
    background_color: "#F7F9FC"
    text_color: "#1F2937"
    accent_color: "#10B981"
    danger_color: "#EF4444"
```

## CLI

```bash
python -m news2docx.cli.main --help
```

- `run`：端到端（抓取 + 两步处理），可选导出 DOCX。
- `scrape`：调用抓取端点/本地 GDELT，抓正文并保存 JSON。
- `process`：字数调整 + 翻译，保持段落对齐，输出处理 JSON。
- `export`：生成 DOCX（可按篇拆分）。
- `doctor`：体检环境变量与端点连通性（不触发计费）。
- `stats`/`clean`/`resume`/`combine`：辅助命令。

## Config

参考示例见 `config.yml`，关键字段：

- 抓取：`crawler_mode`（remote|local）、`crawler_api_url`、`crawler_api_token`、`max_urls`、`concurrency`、`retry_hours`、`timeout`、`pick_mode`、`random_seed`、`db_path`、`noise_patterns`
- 处理：`openai_api_base`、`openai_api_key`、`target_language`、`merge_short_paragraph_chars`
- 导出：`run_export`、`export_split`、`export_order`（`zh-en`|`en-zh`）、`export_mono`、`export_out_dir`、`export_first_line_indent_cm`、`export_font_*`、`export_title_bold`、`export_title_size_multiplier`
 - 处理净化：
   - `processing_forbidden_prefixes`：按行前缀丢弃（如 `Note:`、媒体名、广告提示等）
   - `processing_forbidden_patterns`：按正则丢弃（如日期时间戳/媒体尾注）
   - `processing_min_words_after_clean`：清理后英文最小词数（过低则回退清理前结果）

示例（节选）：

```yaml
crawler_mode: remote
crawler_api_url: "PUT_YOUR_CRAWLER_API_URL_HERE"
crawler_api_token: "PUT_YOUR_CRAWLER_API_TOKEN_HERE"
openai_api_base: "https://api.siliconflow.cn/v1"
openai_api_key: "PUT_YOUR_OPENAI_COMPATIBLE_API_KEY_HERE"
max_urls: 3
export_split: true
export_order: en-zh
```

## Environment Vars

- 抓取：`CRAWLER_API_URL`、`CRAWLER_API_TOKEN`、`CRAWLER_MAX_URLS`、`CRAWLER_TIMEOUT`、`CRAWLER_RETRY_HOURS`、`CRAWLER_MAX_API_ROUNDS`、`CRAWLER_PER_URL_RETRIES`、`CRAWLER_PICK_MODE`、`CRAWLER_RANDOM_SEED`
- 处理：`OPENAI_API_KEY`、`OPENAI_API_BASE`、`OPENAI_MODEL`、`CONCURRENCY`、`N2D_CACHE_DIR`、`OPENAI_MIN_INTERVAL_MS`、`MAX_TOKENS_HARD_CAP`
- 导出：`TARGET_LANGUAGE`、`EXPORT_ORDER`、`EXPORT_MONO`
- 其他：`RUNS_DIR`、`SCRAPER_SELECTORS_FILE`

Windows PowerShell：

```powershell
$env:CRAWLER_API_TOKEN = "your_token"
$env:OPENAI_API_KEY = "your_api_key"
$env:OPENAI_API_BASE = "https://api.siliconflow.cn/v1"
```

Bash：

```bash
export CRAWLER_API_TOKEN="your_token"
export OPENAI_API_KEY="your_api_key"
export OPENAI_API_BASE="https://api.siliconflow.cn/v1"
```

## Crawler Modes

- remote（默认）：通过你部署的中转端点返回 URL，再本地抓正文。
- local：本地直连 GDELT Doc 2.0；站点清单在 `server/news_website.txt`（每行一条，支持 `#` 注释）。

`config.yml` 配置示例：

```yaml
# Remote
crawler_mode: remote
crawler_api_url: https://<your-crawler-endpoint>
crawler_api_token: <your-token>

# Local (GDELT)
# crawler_mode: local
# crawler_sites_file: server/news_website.txt
# gdelt_timespan: 7d
# gdelt_max_per_call: 50
# gdelt_sort: datedesc
```

覆盖同名环境变量：`CRAWLER_MODE`、`CRAWLER_API_URL`、`CRAWLER_API_TOKEN`、`CRAWLER_SITES_FILE`、`GDELT_TIMESPAN`、`GDELT_MAX_PER_CALL`、`GDELT_SORT`。

## Examples

- 端到端导出单文件：

```bash
python -m news2docx.cli.main run --config config.yml --export --no-split -o news.docx
```

- 端到端按篇导出（默认）：

```bash
python -m news2docx.cli.main run --config config.yml --export --split
```

- 仅导出最近一次处理结果：

```bash
python -m news2docx.cli.main export
```

- 合并多份处理结果：

```bash
python -m news2docx.cli.main combine processed_news_*.json -o merged.json
```

## Troubleshooting

- 缺少 `CRAWLER_API_TOKEN`（remote 模式）：使用 `--api-token` 或设置环境变量，或切换到 local 模式。
- 缺少 `OPENAI_API_KEY`：在配置或环境变量中提供；可用 `doctor` 检查连通性。
- 无法直连 GDELT（local 模式）：切换到 remote 模式，或确保网络可达。
- 导出目录：默认 `Desktop/英文新闻稿`（若未显式配置 `export_out_dir`）。

## Server (Optional)

- `server/index.py` 提供云函数事件函数示例，返回近 7 天英文新闻 URL（基于 GDELT Doc 2.0）。
- 站点清单：`server/news_website.txt`；可用 `SITES_FILE` 指定外部路径。
- 云端环境变量：`SITES`、`TIMESPAN`、`MAX_PER_CALL`、`SORT`。
- 返回结构：`{"count": N, "urls": ["https://..."]}`。

## Development

```bash
pytest -q
python scripts/smoke.py
```

## License

暂未声明开源许可证；在生产/商用前请与作者确认授权条款。

