# News2Docx

轻量、可配置的英文新闻到 DOCX 工具：抓取 URL、并发抓正文、AI 清洗与翻译，一键导出规范排版文档（Rich TUI）。

![python](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

English summary: Fetch English news, clean and translate to Chinese with free models, then export nicely formatted DOCX via a Rich TUI.

## 项目概览

- 一键端到端：Rich TUI 提供抓取 → 处理 → 导出全流程。
- 抓取稳定：直连 GDELT Doc 2.0，内置站点清单与内容选择器，可通过文件覆盖。
- 并发与去噪：多线程抓取，启发式噪声清理（登录提示/版权/广告等）。
- AI 流水线（免费通道）：自动选择硅基流动免费模型并发首个成功结果；段落对齐翻译；最小词数筛选与清洗。
- DOCX 导出：每篇独立导出，英文在前→中文在后；标题居中、首行缩进；中英文字体可配；标题默认加粗。
- 可运维：强制 HTTPS、健康检查、统一日志与本地缓存。

## 快速开始

### 依赖
- Python 3.11+
- 可访问外网（GDELT 与硅基流动 API）；仅使用 HTTPS 连接

### 安装
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 运行（最短路径）
```bash
python index.py
```
- 首次启动会提示粘贴 API Key（硅基流动）。也可预先设置环境变量：
  - Bash: `export SILICONFLOW_API_KEY=your_key`
  - PowerShell: `$env:SILICONFLOW_API_KEY = "your_key"`

### 最小配置（自动创建）
首次运行若不存在 `config.yml`，会自动生成最小模板；常用字段示例：
```yaml
openai_api_key: ""
processing_word_min: 350
merge_short_paragraph_chars: 80
export_font_zh_name: 宋体
export_font_zh_size: 10.5
export_font_en_name: Cambria
export_font_en_size: 10.5
export_title_bold: true
```

## 使用示例与输出

- 启动 TUI：`python index.py`
- 体检：在主菜单选择“体检”检查网络、API Key、GDELT 可达性以及导出/运行目录。
- 路径与产物：
  - 抓取与处理：`runs/<run_id>/scraped.json`、`runs/<run_id>/processed.json`
  - 导出目录：桌面 `Desktop/英文新闻稿`（自动创建）
  - 日志：根目录 `log.txt`（控制台与文件双写，启动前清空旧日志）

## 配置与环境变量

说明：部分参数已在代码层固定（如 API Base、导出目录、并发安全上限等），下列项为常用可调参数：

- 处理相关（config.yml）
  - `openai_api_key`：硅基流动/OPENAI 兼容 Key（也可用环境变量）
  - `processing_word_min`：英文最小词数下限（低于该值的文章在免费通道会被跳过）
  - `merge_short_paragraph_chars`：合并短段（基于词数的近似控制）
  - `processing_forbidden_prefixes`：按前缀行丢弃
  - `processing_forbidden_patterns`：按正则行丢弃
- 导出相关（config.yml）
  - `export_font_zh_name`/`export_font_zh_size`、`export_font_en_name`/`export_font_en_size`
  - `export_title_bold`：标题是否加粗
- 环境变量（示例）
  - 密钥：`SILICONFLOW_API_KEY`（优先）或 `OPENAI_API_KEY`
  - 选择器覆盖：`SCRAPER_SELECTORS_FILE=/path/to/selectors.yml`
  - AI 调用：`N2D_CHAT_TIMEOUT`（默认20秒）、`OPENAI_MIN_INTERVAL_MS`（限速），`MAX_TOKENS_HARD_CAP`
  - 词数下限（可替代 config）：`N2D_WORD_MIN`

固定策略（不可改）：
- OpenAI-Compatible Base 固定为 `https://api.siliconflow.cn/v1`（强制 HTTPS）
- 默认“按篇导出”，每篇“英文在前、中文在后”
- 导出目录固定：桌面 `Desktop/英文新闻稿`

## 健康检查（TUI 内置）

- 网络连通性（Cloudflare 探测）
- 硅基流动 API Key 校验（/user/info）
- GDELT 基础可达与最小查询
- 导出目录与 `runs/` 目录可写性

## 常见问题（FAQ）

- Q：启动提示缺少 API Key？
  - A：在 TUI 内粘贴，或设置 `SILICONFLOW_API_KEY`/`OPENAI_API_KEY` 后重启。
- Q：GDELT 访问异常或限流？
  - A：稍后重试；或更换网络环境。体检会展示 HTTP 状态以便定位。
- Q：导出文件在哪？
  - A：统一导出到桌面 `Desktop/英文新闻稿`；每篇新闻一个 DOCX 文件。
- Q：如何调整中英文的字体与字号？
  - A：在 `config.yml` 中修改 `export_font_*` 字段，保存后重试导出。
- Q：如何清除已抓网址缓存以强制重新抓取？
  - A：TUI 主菜单选择“清除已抓网址缓存”。
- Q：如何自定义站点选择器？
  - A：编写选择器配置文件并通过 `SCRAPER_SELECTORS_FILE` 指定路径。

## 贡献指南（简版）

- 分支：从 `main` 派生特性分支；PR 前请先关联 Issue。
- 规范：Ruff（lint）+ Black（格式），行宽 100；类型检查（mypy，若使用）。
- 测试：新增/变更必须补充或更新测试；统一入口 `python -m pytest -q`。
- 提交：清晰的动机与“为什么”；避免堆叠无关改动。

（更详细流程将补充到 CONTRIBUTING.md）

## 开发与测试

```bash
# 运行测试
python -m pytest -q

# 代码检查与格式化（可选）
ruff check .
ruff format .
```

## 版本日志

将随后续版本补充 `CHANGELOG.md`，记录新增、修复与潜在破坏性变更。

## 许可证

暂未声明开源许可证；在生产/商用前请与作者确认授权条款。

