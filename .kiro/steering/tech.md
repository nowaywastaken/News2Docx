# Technology Stack

## Core Technologies

- **Python**: 3.11+ required
- **UI Framework**: Rich (terminal-based TUI)
- **Document Generation**: python-docx
- **Web Scraping**: requests + BeautifulSoup4
- **Configuration**: PyYAML
- **AI Integration**: OpenAI-compatible API (SiliconFlow)

## Key Dependencies

```
requests==2.32.3
beautifulsoup4==4.12.3
python-docx==0.8.11
pyyaml==6.0.2
tenacity==8.2.3
rich==13.7.1
```

## Development Tools

- **Linting**: Ruff (replaces flake8/isort)
- **Formatting**: Black (line length: 100)
- **Testing**: pytest
- **Type Checking**: mypy (optional, configured but not strict)
- **Packaging**: PyInstaller for distribution

## Common Commands

### Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Development
```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run application
python index.py

# Code quality
ruff check .
ruff format .
black .

# Testing
python -m pytest -q
```

### Configuration

- **Main config**: `config.yml` (auto-created on first run)
- **API Keys**: Environment variables preferred (`SILICONFLOW_API_KEY`)
- **Logging**: Dual output to console + `log.txt`

## Architecture Constraints

- **HTTPS Only**: All external requests must use HTTPS
- **No CLI Args**: Single entry point via `python index.py`
- **TUI Only**: Rich-based terminal interface (PyQt removed)
- **Fixed API Base**: SiliconFlow endpoint hardcoded for consistency