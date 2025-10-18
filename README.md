# News2Docx

轻量、可配置的英文新闻到 DOCX 工具：抓 URL、并发抓正文、AI 控字与翻译、导出规范排版文档。

![python](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

English summary: Fetch English news, condense to target length, translate to Chinese, and export nicely formatted DOCX via a Rich-based TUI.

## Features

- 简洁：单命令端到端，或按阶段拆分运行。
- 抓取模式：仅本地（直连 GDELT Doc 2.0）。
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
pip install -r requirements-dev.txt  # 开发者可选
```

可选冒烟（不联网，仅验证导出链路）：

```bash
python scripts/smoke.py
```

## Quick Start

1) 编辑配置 `config.yml`，至少填入：

- `openai_api_key`（OpenAI-Compatible，必填）

2) 端到端运行（Rich TUI）：

```bash
python index.py
```

## UI（Rich）

- 启动：`python index.py` 或 `python -m news2docx.tui.tui`（自动读取根目录 `config.yml`）
- 功能：一键运行；分阶段运行（抓取/处理/导出）；查看与少量编辑关键配置；可基于最近上下文重试
- 日志：程序启动前清空根目录 `log.txt`；运行过程中同时写入终端与 `log.txt`

函数说明（index.py）：
- `load_app_config(config_path)`：加载配置（严格读取指定路径）。
- `prepare_logging(log_file)`：初始化日志（终端 + `log.txt`）。
- `run_scrape(conf)`：执行抓取，保存 `scraped_news_*.json`。
- `run_process(conf, scraped_json_path)`：两步处理，写入 `runs/<id>/processed.json`。
- `run_export(conf, processed_json_path)`：按配置导出 DOCX（单文件或分篇）。

## UI（Rich TUI）

- 启动：`python -m news2docx.tui.tui`
- 功能：
  - 一键运行：抓取 → 处理 → 导出，展示阶段进度与耗时
  - 配置：查看/修改关键配置（openai_api_base/Key、模型与基础参数）
  - 体检：检查 OPENAI_API_KEY、openai_api_base(HTTPS)、端点连通、导出与 runs 目录
  - 退出
- 日志：沿用 `log.txt` 与终端同步输出；异常时在面板提示并引导查看日志。

安全配置：已移除字段级加密功能。`secure_load_config` 仅做普通配置读取，不会修改文件。

（UI 相关配置项已移除，不再需要 app/ui 设置）

（项目已全面改用 Rich TUI，CLI 已移除）

## Config

参考示例见 `config.yml`，关键字段：

- 抓取：`max_urls`、`concurrency`、`retry_hours`、`timeout`、`pick_mode`、`random_seed`、`db_path`、`noise_patterns`（已在代码写死，此处设置不再生效）
- 处理：`openai_api_base`、`openai_api_key`、`target_language`、`merge_short_paragraph_chars`
  - 模型选择（支持分离）：
    - `openai_model_general`：通用模型（英文编辑/控字等）
    - `openai_model_translation`：翻译模型（标题翻译与正文翻译）
    - 兼容：`openai_model`（如仅设置此字段，将同时用于上述两类场景）
- 导出：`run_export`、`export_split`、`export_order`（`zh-en`|`en-zh`）、`export_mono`、`export_out_dir`、`export_first_line_indent_inch`、`export_font_*`、`export_title_bold`、`export_title_size_multiplier`
 - 处理净化：
   - `processing_forbidden_prefixes`：按行前缀丢弃（如 `Note:`、媒体名、广告提示等）
   - `processing_forbidden_patterns`：按正则丢弃（如日期时间戳/媒体尾注）
   - `processing_min_words_after_clean`：清理后英文最小词数（过低则回退清理前结果）

示例（节选）：

```yaml
openai_api_base: "https://api.siliconflow.cn/v1"
openai_api_key: "PUT_YOUR_OPENAI_COMPATIBLE_API_KEY_HERE"
max_urls: 10
export_split: true
export_order: en-zh

# 分离模型设置（推荐）
openai_model_general: "gpt-4o-mini"
openai_model_translation: "qwen-2.5-7b-instruct"
```

## Environment Vars

- 处理：`OPENAI_API_KEY`、`OPENAI_API_BASE`、`OPENAI_MODEL`、`CONCURRENCY`、`N2D_CACHE_DIR`、`OPENAI_MIN_INTERVAL_MS`、`MAX_TOKENS_HARD_CAP`
- 其他：`SCRAPER_SELECTORS_FILE`

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = "your_api_key"
$env:OPENAI_API_BASE = "https://api.siliconflow.cn/v1"
```

Bash：

```bash
export OPENAI_API_KEY="your_api_key"
export OPENAI_API_BASE="https://api.siliconflow.cn/v1"
```

## Crawler

仅保留本地直连 GDELT Doc 2.0；站点清单与查询参数将随爬虫重写一并调整（当前配置项已不再读取）。

文档与 UML：`docs/uml.wsd`（PlantUML）

（使用 TUI 执行一键或分阶段操作，无需 CLI 示例）

## Troubleshooting

- 缺少 `OPENAI_API_KEY`：在配置或环境变量中提供；TUI 启动时会自动进行健康检查并提示连通性。
- 无法直连 GDELT：请确保网络可达或调整 `gdelt_timespan` 等参数。
- 导出目录：默认 `Desktop/英文新闻稿`（若未显式配置 `export_out_dir`）。

## Server (Optional)

- `server/index.py` 提供云函数事件函数示例，返回近 7 天英文新闻 URL（基于 GDELT Doc 2.0）。
- 站点清单：`server/news_website.txt`；可用 `SITES_FILE` 指定外部路径。
- 云端环境变量：`SITES`、`TIMESPAN`、`MAX_PER_CALL`、`SORT`。
- 返回结构：`{"count": N, "urls": ["https://..."]}`。

## Development

```bash
# 统一测试入口（合并为单文件）
python -m pytest -q

# 可选冒烟测试
python scripts/smoke.py
```

## Package (PyInstaller)

- 依赖安装：确保已安装 `pyinstaller`（已在 `requirements.txt` 中）。
- 打包命令：

```bash
python scripts/build_pyinstaller.py
```

- 输出位置：`dist/news2docx/`（onedir 模式更稳定）。
- 运行方式：在含有你的 `config.yml` 的目录下运行其中的可执行文件；或将 `config.yml` 放到可执行文件同级目录。
- 安全：打包不会包含你的 `config.yml`（避免泄露密钥）。示例 `config.example.yml` 会被一并打包用于指引。

## License

暂未声明开源许可证；在生产/商用前请与作者确认授权条款。
