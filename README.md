# News2Docx

## Environment Variables

The application requires API credentials to be provided via environment variables, command line arguments, or a JSON/YAML configuration file.

- CRAWLER_API_TOKEN: Token for the crawler API.
- SILICONFLOW_API_KEY: API key for the SiliconFlow service.

Example (bash):

```bash
export CRAWLER_API_TOKEN="your_crawler_token"
export SILICONFLOW_API_KEY="your_siliconflow_key"
```

You may also pass these values using the command line options `--api-token` and `--siliconflow-api-key` or supply a config file via `--config` with fields `crawler_api_token` and `siliconflow_api_key`.

## 新的 CLI（Phase 1-2）

- 抓取：
  - `python -m news2docx.cli.main scrape --api-token $CRAWLER_API_TOKEN --max-urls 3`
- 处理（两步法：词数调整 → 翻译）：
  - `python -m news2docx.cli.main process scraped_news_YYYYMMDD_HHMMSS.json --target-language Chinese`
- 端到端：
  - `python -m news2docx.cli.main run --api-token $CRAWLER_API_TOKEN --max-urls 3`
- 导出 DOCX（Phase 2 新增）：
  - `python -m news2docx.cli.main export processed_news_YYYYMMDD_HHMMSS.json -o out.docx --order zh-en`
- 体检：
  - `python -m news2docx.cli.main doctor`

说明：
- LLM 仅使用硅基流动（SiliconFlow），需要 `SILICONFLOW_API_KEY`。
- `export` 子命令默认中英双语（中文在前），可通过 `--mono` 仅输出中文，或 `--order en-zh` 调整顺序。

## 配置文件示例

支持 JSON 或 YAML（优先级：CLI > 环境变量 > 配置文件 > 默认值）。

示例 YAML (config.yml):

```yaml
# Crawler
crawler_api_url: https://gdelt-xupojkickl.cn-hongkong.fcapp.run
crawler_api_token: YOUR_TOKEN

# LLM
siliconflow_api_key: YOUR_SF_KEY

# Scrape
max_urls: 3
concurrency: 4
retry_hours: 24
timeout: 30
strict_success: true
max_api_rounds: 5
per_url_retries: 2
pick_mode: random
random_seed: 42

# Process
target_language: Chinese

# Export
export_order: zh-en
export_mono: false
```

使用：
- `python -m news2docx.cli.main run --config config.yml`
- `python -m news2docx.cli.main scrape --config config.yml`
- `python -m news2docx.cli.main process scraped.json --config config.yml`
- `python -m news2docx.cli.main export processed.json --config config.yml -o out.docx`

### 健康检查（doctor）

`doctor` 会检查：
- 必需环境变量：`CRAWLER_API_TOKEN`、`SILICONFLOW_API_KEY`
- 端点连通性：尝试对爬虫 API 与 SiliconFlow 端点发起 GET（不进行实际业务调用），只要无网络错误即视为可达。
