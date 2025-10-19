# Product Overview

News2Docx is a lightweight, configurable tool for scraping English news articles and exporting them to formatted DOCX documents with AI-powered translation.

## Core Features

- **End-to-end pipeline**: Scrape → Process → Export workflow via Rich TUI
- **News scraping**: Fetches articles from GDELT Doc 2.0 API with concurrent processing
- **AI translation**: Uses SiliconFlow free models for Chinese translation with paragraph alignment
- **DOCX export**: Per-article export with configurable fonts, formatting (English first, Chinese second)
- **Noise filtering**: Heuristic cleaning of ads, login prompts, copyright notices
- **Caching**: Local SQLite cache to avoid re-scraping URLs

## Target Users

Users who need to:
- Collect and translate English news articles to Chinese
- Generate formatted Word documents with bilingual content
- Automate news aggregation workflows

## Key Constraints

- Requires external network access (GDELT and SiliconFlow API)
- HTTPS-only connections enforced
- Fixed export directory: Desktop/英文新闻稿
- Fixed API base: https://api.siliconflow.cn/v1
- Minimum word count filtering (default 350 words)
