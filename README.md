# News2Docx

将海外英文新闻一键抓取、精炼（控制字数与段落）、机器翻译成中文，并按排版要求导出为 Word（DOCX）文档。内置命令行工具，支持端到端处理或对任一阶段单独运行。

- 抓取来源：通过可配置的聚合爬取 API 获取新闻链接，内置常见站点的提取选择器，并支持自定义覆盖。
- 文本处理：并发调用大模型接口（SiliconFlow 兼容 OpenAI Chat Completions）完成“字数调整 + 双语翻译”，保持中英文段落对齐。
- 文档导出：按教辅/作文材料常用规范导出 DOCX（标题居中、首行缩进、中文宋体/英文字体可配），可合并导出或按篇拆分导出。


## 运行环境

- Python 3.11+（推荐 3.11/3.12）
- 操作系统：Windows / macOS / Linux
- 需要外网访问权限（抓取 API 与 LLM 接口）


## 安装

- 克隆本仓库后，使用虚拟环境安装依赖：

```
python -m venv .venv
.venv/Scripts/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- 可选：本地快速冒烟测试（不联网）：

```
python scripts/smoke.py
```


## 快速开始

1) 复制并编辑配置文件

- 将根目录的 `config.example.yml` 复制为 `config.yml`，填入必需项：
  - `crawler_api_url`: 抓取 API 的地址
  - `crawler_api_token`: 抓取 API 的 Token（必填）
  - `siliconflow_api_key`: SiliconFlow 的 API Key（必填，用于 AI 处理）

2) 运行端到端流程（抓取 → 处理 → 导出）

```
python -m news2docx.cli.main run --config config.yml
```

- 首次运行会在项目根目录创建 `runs/<时间戳>/`，并生成：
  - `scraped.json`: 抓取并抽取后的原文数据
  - `processed.json`: AI 字数调整与翻译后的结果
- 若启用导出，将在桌面自动创建中文文件夹 `英文新闻稿` 并导出 DOCX（可配置输出目录）。

3) 只抓取或只处理或只导出

```
# 仅抓取并保存 scraped_news_*.json
python -m news2docx.cli.main scrape --config config.yml --max-urls 3

# 仅处理（输入为上一步保存的 JSON）
python -m news2docx.cli.main process scraped_news_20240101_120000.json --config config.yml

# 仅导出（默认选取最新 runs/*/processed.json）
python -m news2docx.cli.main export --config config.yml --split/--no-split
```


## 命令行用法

所有命令都可通过 `--help` 查看参数说明：

```
python -m news2docx.cli.main --help
```

- scrape：调用抓取 API 获取 URL，并并发抓取网页正文，保存为 JSON。
- process：对抓取结果进行“两步处理”（字数调整 → 翻译），输出处理后的 JSON。
- run：端到端执行（抓取 → 处理），并可选导出 DOCX。
- export：将处理结果导出为 DOCX（支持按篇拆分）。
- doctor：体检命令，检查必需环境变量与接口可达性。
- stats：查看 `runs` 目录统计与最近一次运行 ID。
- clean：清理旧的 `runs/*` 目录，默认保留最近 3 个。
- resume：在最新 `runs/<id>` 下若缺少 processed.json，则用 scraped.json 继续处理。
- combine：将多个 `processed_news_*.json` 合并为一个。

常用示例：

```
# 指定导出参数：中英段落顺序、是否只导出中文
python -m news2docx.cli.main run --config config.yml --export --order en-zh --mono false

# 按篇拆分导出（文件名用中文标题自动去噪）
python -m news2docx.cli.main export --config config.yml --split

# 体检（不实际发起 LLM 计费请求）
python -m news2docx.cli.main doctor --config config.yml
```


## 配置说明

支持通过“配置文件 + 环境变量 + 命令行参数”覆盖合并，后者优先级更高。

- 配置文件：`config.yml`（示例见 `config.example.yml`）
- 环境变量：部署时更方便注入，如 Docker/CI/服务器
- 命令行参数：一次性临时覆盖

核心配置项（与当前实现对应）：

- 抓取相关
  - `crawler_api_url`：抓取 API 地址（默认内置一条演示地址）
  - `crawler_api_token`：抓取 API Token（必填）
  - `max_urls`：本次抓取最多 URL 数
  - `concurrency`：抓取并发数
  - `timeout`：单次请求超时秒数
  - `pick_mode`：`random` 或 `top`，决定从候选 URL 池的取样策略
  - `random_seed`：随机种子（取样可复现）
  - `db_path`：SQLite 路径，用于记录已抓取 URL，避免重复
  - `noise_patterns`：额外噪声文本关键词，辅助去噪

- 处理相关（AI）
  - `siliconflow_api_key`：必填，LLM API Key
  - `target_language`：目标语言（默认中文）
  - `merge_short_paragraph_chars`：合并过短英文段落的阈值（字符数，默认 80）
  - 其他可通过环境变量控制（见下一节）：
    - `SILICONFLOW_MODEL`（默认 `THUDM/glm-4-9b-chat`）
    - `SILICONFLOW_URL`（默认 `https://api.siliconflow.cn/v1/chat/completions`）
    - `CONCURRENCY`（处理阶段并发，默认 4）
    - `N2D_CACHE_DIR`（本地去重缓存目录，默认 `.n2d_cache`）
    - `SF_MIN_INTERVAL_MS`（两次 LLM 调用的最小间隔，节流）

- 导出相关（DOCX）
  - `run_export`：在 run 命令中自动导出（等价 `--export`）
  - `export_split`：是否按篇拆分导出（等价 `--split`，默认 True）
  - `export_order`：段落顺序 `en-zh` 或 `zh-en`
  - `export_mono`：仅导出中文（不含英文）
  - `export_out_dir`：导出目录（默认桌面 `英文新闻稿`）
  - 字体与版式：`export_first_line_indent_cm`、`export_font_zh_*`、`export_font_en_*`、`export_title_bold`、`export_title_size_multiplier`

环境变量快速参考（可与配置文件混用）：

- 抓取：`CRAWLER_API_URL`、`CRAWLER_API_TOKEN`、`CRAWLER_MAX_URLS`、`CRAWLER_TIMEOUT`、`CRAWLER_PICK_MODE`、`CRAWLER_RANDOM_SEED`
- 处理：`SILICONFLOW_API_KEY`、`SILICONFLOW_URL`、`SILICONFLOW_MODEL`、`CONCURRENCY`、`N2D_CACHE_DIR`、`SF_MIN_INTERVAL_MS`
- 导出：`TARGET_LANGUAGE`、`EXPORT_ORDER`、`EXPORT_MONO`


## 输出与目录结构

- `runs/<YYYYMMDD_HHMMSS>/scraped.json`：抓取到的文章原文与元信息
- `runs/<YYYYMMDD_HHMMSS>/processed.json`：处理后的双语结果
- `Desktop/英文新闻稿/`：默认导出 DOCX 的目录（可通过配置修改）

项目关键目录：

- `news2docx/cli/main.py`：命令行入口及各子命令
- `news2docx/scrape/`：抓取逻辑、提取规则与选择器覆盖
- `news2docx/process/engine.py`：两步处理（字数调整 + 翻译）并发引擎
- `news2docx/export/docx.py`：DOCX 导出与排版实现
- `news2docx/core/`：通用配置与工具函数


## 自定义选择器（可选）

部分站点的标题/正文选择器可通过文件覆盖：

- 编写一个 JSON/YAML 文件，结构如下（示例）：

```
{
  "bbc.com": {
    "title":   ["h1[data-testid=\"headline\"]", "h1"],
    "content": ["[data-component=\"text-block\"] p", "article p", "p"],
    "remove":  [".ad", "script", "style", "nav", "aside"]
  }
}
```

- 运行前设置环境变量 `SCRAPER_SELECTORS_FILE=/path/to/your_selectors.yml`，程序会在内置规则基础上合并你的覆盖项。


## 常见问题（FAQ）

- 没有 Token/API Key 怎么办？
  - 抓取阶段需要 `CRAWLER_API_TOKEN`，处理阶段需要 `SILICONFLOW_API_KEY`。任一缺失都会导致对应阶段无法运行。
- 为什么导出的 DOCX 是中文命名目录？
  - 为方便区分与快速定位，默认导出到桌面中文文件夹 `英文新闻稿`；你也可以在配置中改为任意路径。
- 运行 `process/run` 报错：缺少 `SILICONFLOW_API_KEY`？
  - 请在 `config.yml` 或环境变量中提供该 Key。`doctor` 子命令可以帮助检查配置与连通性。
- YAML 配置读不出来？
  - 需要安装 `PyYAML`。本项目默认已在 `requirements.txt` 中包含；也可改用 JSON 格式配置文件。
- 字数控制不精确？
  - 引擎会在 400–450 词范围内多次尝试调整，但受模型输出影响，极端情况下可能略有偏离。


## 贡献与开发

- 代码风格：`black`（100 列）与 `ruff`（E/F/I）
- 测试：
  - 单元测试示例位于 `tests/`，可使用 `pytest -q` 运行（需自行安装 pytest）。
  - 日常本地验证可运行 `scripts/smoke.py`。


## 风险与注意事项

- 请合理保存 `config.yml` 与 API Key，不要提交到公共仓库。
- 抓取与处理均依赖第三方服务，请遵守目标网站与 API 使用条款。
- 生成式模型输出可能包含错误或偏差，请在人审后再正式使用。


## 许可证

本项目未显式声明开源许可证。若需在生产环境或商用场景中使用，请先与作者确认授权条款。

