# News2Docx

一键抓取英文新闻，自动控字与双语翻译，导出为排版规范的 DOCX 文档。
English summary: Fetch English news, condense to target length, translate to Chinese, and export nicely formatted DOCX via a simple CLI.

- 抓取来源：可配置聚合 API 返回 URL；内置常见站点正文选择器，支持自定义覆盖。
- 文本处理：并发调用 LLM（SiliconFlow Chat Completions 兼容）完成“字数调整 + 双语翻译”，保持段落对齐。
- 文档导出：按教辅/作文材料常用规范生成 DOCX（标题居中、首行缩进、可配置中英字体），支持合并导出或按篇拆分。

## 环境要求

- Python 3.11+（推荐 3.11/3.12）
- Windows / macOS / Linux
- 可访问外网（抓取 API 与 LLM 接口）

## 安装

使用虚拟环境安装依赖：
```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

可选：本地冒烟（不联网，仅验证导出链路）：
```bash
python scripts/smoke.py
```

## 快速开始
1) 复制并编辑配置文件
- 将根目录下 `config.example.yml` 复制为 `config.yml`，填写：
  - `crawler_api_url`：抓取 API 地址
  - `crawler_api_token`：抓取 API Token（必填）
  - `siliconflow_api_key`：SiliconFlow API Key（必填，用于 AI 处理）
2) 一条命令端到端（抓取 + 处理 + 可选导出）

```bash
python -m news2docx.cli.main run --config config.yml
```

- 会在 `runs/<时间戳>/` 生成：
  - `scraped.json`：抓取并抽取后的原文数据
  - `processed.json`：字数调整与翻译后的结果
- 如开启导出，将在桌面自动创建目录“英文新闻稿”并导出 DOCX（可在配置中修改输出目录）。

3) 分阶段运行（只抓取 / 只处理 / 只导出）

```bash
# 仅抓取并保存 scraped_news_*.json
python -m news2docx.cli.main scrape --config config.yml --max-urls 3

# 仅处理（输入为上一步保存的 JSON），输出 processed_news_*.json
python -m news2docx.cli.main process scraped_news_20240101_120000.json --config config.yml

# 仅导出（默认选取最新 runs/*/processed.json）
python -m news2docx.cli.main export --config config.yml --split/--no-split
```

## 命令行用法
所有命令均支持 `--help` 查看参数说明：
```bash
python -m news2docx.cli.main --help
```

- `scrape`：调用抓取 API 获取 URL，并发抓取网页正文，保存为 JSON。
  - 常用参数：`--api-token`、`--api-url`、`--max-urls`、`--concurrency`、`--timeout`、`--retry-hours`、`--strict-success/--no-strict-success`、`--max-api-rounds`、`--per-url-retries`、`--pick-mode [random|top]`、`--random-seed`、`--config`。
  - 说明：首次使用会在 `.n2d_cache/crawled.sqlite3` 维护已抓取 URL，避免重复。

- `process`：对抓取结果执行“两步处理”（字数调整 + 翻译），输出处理后的 JSON。
  - 参数：`<input_json>`、`--target-language`（默认 Chinese）、`--config`。
  - 输出：`processed_news_<时间戳>.json`（当前目录）。

- `run`：端到端执行（抓取 + 处理），并可选导出 DOCX。
  - 抓取参数同 `scrape`；处理参数同 `process`。
  - 导出相关：`--export/--no-export`、`--order [zh-en|en-zh]`、`--mono`（仅中文）、`--split/--no-split`（默认拆分导出）、`--output`（文件或目录）。
  - 输出：`runs/<时间戳>/scraped.json`、`runs/<时间戳>/processed.json`；如导出则在“英文新闻稿”（或自定义目录）生成 DOCX。

- `export`：将处理结果导出为 DOCX（支持按篇拆分）。
  - 参数：`[processed_json]`（可省略，自动取最新 `runs/*/processed.json`）、`--order`、`--mono`、`--split/--no-split`、`--output`、`--config`。

- `doctor`：体检命令，检查关键环境变量与网络连通性（不触发真实计费调用）。

- `stats`：查看 `runs` 目录统计与最近一次运行的 ID。

- `clean`：清理旧的 `runs/*` 目录，默认保留最新 3 个（`--keep N` 可调）。

- `resume`：从最近一次 `runs/<id>` 继续，如缺少 `processed.json` 则基于 `scraped.json` 生成。

- `combine`：将多个 `processed_news_*.json` 合并为一个（`-o/--output` 指定输出路径）。

常用示例：
```bash
# 指定导出参数：段落顺序与是否仅导出中文
python -m news2docx.cli.main run --config config.yml --export --order en-zh --mono false

# 按篇拆分导出（文件名使用中文标题自动去噪）
python -m news2docx.cli.main export --config config.yml --split

# 体检（网络连通性与关键环境变量）
python -m news2docx.cli.main doctor
```

## 配置说明（config.yml）
示例参考 `config.example.yml`。关键项：

- 抓取相关
  - `crawler_api_url`：抓取 API 地址
  - `crawler_api_token`：抓取 API Token（必填）
  - `max_urls`、`concurrency`、`retry_hours`、`timeout`、`strict_success`、`max_api_rounds`、`per_url_retries`、`pick_mode`（random/top）
  - `random_seed`：固定随机种子（可选）
  - `db_path`：去重数据库路径（默认 `.n2d_cache/crawled.sqlite3`）
  - `noise_patterns`：额外噪声关键词（辅助去噪）

- 处理相关（AI）
  - `siliconflow_api_key`：必填，LLM API Key
  - `target_language`：目标语言（默认 Chinese）
  - `merge_short_paragraph_chars`：英文过短段落的合并阈值（默认 80 字符）

- 导出相关（DOCX）
  - `run_export`：在 `run` 命令中自动导出（等价 `--export`）
  - `export_split`：是否按篇拆分（等价 `--split`，默认 True）
  - `export_order`：段落顺序 `en-zh` 或 `zh-en`
  - `export_mono`：仅导出中文（不含英文）
  - `export_out_dir`：导出目录（默认桌面“英文新闻稿”）
  - 字体与版式：`export_first_line_indent_cm`、`export_font_zh_*`、`export_font_en_*`、`export_title_bold`、`export_title_size_multiplier`

- 运行目录
  - `runs_dir`：自定义 `runs` 根目录（默认 `runs`）

环境变量速查（可与配置文件混用）：
- 抓取：`CRAWLER_API_URL`、`CRAWLER_API_TOKEN`、`CRAWLER_MAX_URLS`、`CRAWLER_TIMEOUT`、`CRAWLER_RETRY_HOURS`、`CRAWLER_STRICT_SUCCESS`、`CRAWLER_MAX_API_ROUNDS`、`CRAWLER_PER_URL_RETRIES`、`CRAWLER_PICK_MODE`、`CRAWLER_RANDOM_SEED`
- 处理：`SILICONFLOW_API_KEY`、`SILICONFLOW_URL`、`SILICONFLOW_MODEL`、`CONCURRENCY`、`N2D_CACHE_DIR`、`SF_MIN_INTERVAL_MS`、`MAX_TOKENS_HARD_CAP`
- 导出：`TARGET_LANGUAGE`、`EXPORT_ORDER`、`EXPORT_MONO`
- 运行目录：`RUNS_DIR`（等价 `runs_dir`）
- 选择器覆盖：`SCRAPER_SELECTORS_FILE`（指向你的 JSON/YAML 覆盖文件）

Windows PowerShell 设置环境变量：
```powershell
$env:CRAWLER_API_TOKEN = "your_token"
$env:SILICONFLOW_API_KEY = "your_api_key"
```

Bash 设置环境变量：
```bash
export CRAWLER_API_TOKEN="your_token"
export SILICONFLOW_API_KEY="your_api_key"
```

## 输出与目录结构
- `runs/<YYYYMMDD_HHMMSS>/scraped.json`：抓取到的文章原文与元信息
- `runs/<YYYYMMDD_HHMMSS>/processed.json`：处理后的双语结果
- `Desktop/英文新闻稿/`：默认 DOCX 导出目录（可通过配置修改）

项目关键目录：
- `news2docx/cli/main.py`：命令行入口与各子命令
- `news2docx/scrape/`：抓取逻辑、提取规则与选择器覆盖
- `news2docx/process/engine.py`：两步处理（字数调整 + 翻译）并发引擎
- `news2docx/export/docx.py`：DOCX 导出与排版实现
- `news2docx/services/`：服务层（processing/exporting/runs）
- `news2docx/core/`：通用配置与工具函数

## 架构与模块（v2 重构）
- CLI 变薄：`news2docx/cli/main.py` 只做参数解析与调度
- 公共辅助：`news2docx/cli/common.py` 负责环境变量注入与桌面目录定位
- 服务层：
  - `news2docx/services/processing.py`：数据转换与处理编排
  - `news2docx/services/exporting.py`：导出配置与写入
  - `news2docx/services/runs.py`：运行目录管理（支持 `RUNS_DIR`/`runs_dir`）
- 向后兼容：命令与参数保持不变；新增 `runs_dir`/`RUNS_DIR` 支持定制输出根目录

## 自定义选择器（可选）
部分站点的正文选择器支持通过文件覆盖：
```json
{
  "bbc.com": {
    "title":   ["h1[data-testid=\"headline\"]", "h1"],
    "content": ["[data-component=\"text-block\"] p", "article p", "p"],
    "remove":  [".ad", "script", "style", "nav", "aside"]
  }
}
```
运行前设置 `SCRAPER_SELECTORS_FILE=/path/to/your_selectors.yml` 或 `.json`，程序会在内置规则基础上合并你的覆盖项。

## 常见问题（FAQ）
- 缺少 Token/API Key？
  - 抓取阶段需要 `CRAWLER_API_TOKEN`，处理阶段需要 `SILICONFLOW_API_KEY`。任一缺失都会导致对应阶段无法运行。
- 为什么导出的 DOCX 使用中文目录名？
  - 为便于区分与快速定位，默认导出到桌面中文文件夹“英文新闻稿”；可在配置中改为任意路径。
- 运行 `process`/`run` 报错：缺少 `SILICONFLOW_API_KEY`？
  - 请在 `config.yml` 或环境变量中提供 API Key。`doctor` 子命令可帮助检查配置与连通性。
- YAML 配置读取失败？
  - 需要安装 `PyYAML`（已在 `requirements.txt` 中）。也可使用 JSON 配置文件。
- 字数控制为何偶有偏差？
  - 引擎会在限定范围内多次尝试调整，受模型输出影响，极端情况下可能略有偏离。

## 开发与测试
- 代码风格：`black`（120 列）、`ruff`（E/F/I）
- 单元测试：位于 `tests/`
- 运行测试（不访问网络）：
```bash
pytest -q
```
- 本地冒烟：
```bash
python scripts/smoke.py
```

## 风险与注意事项
- 请妥善保管 `config.yml` 与 API Key，不要提交到公共仓库。
- 抓取与处理均依赖第三方服务，请遵守目标网站与 API 使用条款。
- 生成式模型输出可能包含错误或偏差，请在人工审校后再正式使用。

## 许可
本项目暂未声明开源许可证。若需在生产或商用场景中使用，请先与作者确认授权条款。
