# News2Docx

## 项目目标
News2Docx 自动化完成“新闻爬取 → AI 处理 → DOCX 生成”流程，帮助用户快速获得带有中英文内容的 Word 文档。

## 主要功能
- **新闻爬取**：`Scraper.py` 调用外部 API 获取新闻 URL，并抓取文章正文【F:Scraper.py†L44-L59】。
- **AI 处理**：`ai_processor.py` 使用 SiliconFlow 模型调整词数并翻译文本【F:ai_processor.py†L47-L60】。
- **文档生成**：`News2Docx_CLI.py` 将处理结果写入 DOCX，支持中英双语段落。

## 典型使用流程
1. 设置所需的环境变量和 API 密钥。
2. 安装依赖。
3. 执行命令行入口 `News2Docx_CLI.py`，完成爬取、处理与文档输出。
4. 在指定目录找到生成的 DOCX 文件。

## 安装与运行
### 环境要求
- Python 3.8+

### 安装步骤
1. 克隆仓库并进入目录。
2. （可选）创建虚拟环境。
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

### 必要环境变量
| 变量名 | 说明 |
|-------|------|
| `SILICONFLOW_API_KEY` | SiliconFlow AI 服务密钥，用于翻译与词数控制。注册 [SiliconFlow](https://siliconflow.cn/) 后在控制台获取。 |
| `CRAWLER_API_URL` | 提供新闻 URL 的 API 入口，默认指向示例服务【F:Scraper.py†L45】 |
| `CRAWLER_API_TOKEN` | 访问新闻 API 的令牌【F:Scraper.py†L46】 |
| `SILICONFLOW_MODEL` | 可选，指定使用的模型 ID【F:ai_processor.py†L47】 |

在运行前先设置环境变量，例如：
```bash
export SILICONFLOW_API_KEY="sk-your-key"
export CRAWLER_API_URL="https://example.com/api"
export CRAWLER_API_TOKEN="token-xxx"
```

## 最简示例
以下命令将抓取一篇新闻，经过 AI 处理后生成 DOCX：
```bash
python3 News2Docx_CLI.py --use-scraper --output-dir output
```
生成的文件位于 `output` 目录。

## 目录结构
```
.
├── News2Docx_CLI.py   # CLI 主程序：爬取、AI 处理与文档生成
├── Scraper.py         # 新闻爬虫模块，可单独运行
├── ai_processor.py    # AI 词数控制与翻译模块
├── requirements.txt   # 项目依赖
└── README.md          # 项目文档
```

