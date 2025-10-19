# Technology Stack

## Language & Runtime

- **Python**: 3.11+ required
- **Platform**: Cross-platform (Windows, macOS, Linux)

## Core Dependencies

- `requests` (2.32.3): HTTP client for API calls and scraping
- `beautifulsoup4` (4.12.3): HTML parsing and content extraction
- `python-docx` (0.8.11): DOCX document generation
- `pyyaml` (6.0.2): Configuration file parsing
- `tenacity` (8.2.3): Retry logic for API calls
- `rich` (13.7.1): Terminal UI framework

## Development Tools

- **Linting**: Ruff (line length 100)
- **Formatting**: Black (line length 100, target py311+)
- **Testing**: pytest
- **Type checking**: mypy (optional, configured but not strictly enforced)

## Project Structure

```
news2docx/
├── ai/           # AI model selection and chat interface
├── cli/          # CLI utilities and common functions
├── core/         # Core models, config, and utilities
├── export/       # DOCX generation logic
├── infra/        # Logging and secure config loading
├── process/      # Article processing engine
├── scrape/       # Web scraping and GDELT integration
├── services/     # High-level orchestration services
└── tui/          # Rich-based terminal UI
```

## Common Commands

### Setup
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run Application
```bash
python index.py
```

### Testing
```bash
python -m pytest -q
```

### Code Quality
```bash
ruff check .      # Lint
ruff format .     # Format
```

## Configuration

- **Main config**: `config.yml` (auto-generated on first run)
- **Environment variables**:
  - `SILICONFLOW_API_KEY` or `OPENAI_API_KEY`: API authentication
  - `N2D_LOG_LEVEL`: Logging verbosity (default: INFO)
  - `N2D_CHAT_TIMEOUT`: AI API timeout (default: 20s)
  - `SCRAPER_SELECTORS_FILE`: Custom selector overrides

## Data Storage

- **Cache**: `.n2d_cache/crawled.sqlite3` (scraped URLs)
- **Runs**: `runs/<run_id>/` (scraped.json, processed.json)
- **Logs**: `log.txt` (root directory, cleared on startup)
- **Export**: `~/Desktop/英文新闻稿/` (fixed location)
