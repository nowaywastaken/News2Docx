# Project Structure

## Root Level

- `index.py` - Single entry point, orchestrates scrape → process → export pipeline
- `config.yml` - Main configuration (auto-created with defaults)
- `goal.yaml` - Detailed system architecture and data flow specification
- `log.txt` - Unified logging output (cleared on startup)
- `requirements.txt` / `requirements-dev.txt` - Dependencies
- `pyproject.toml` - Tool configuration (Black, Ruff, pytest, mypy)

## Package Organization (`news2docx/`)

### Core Modules
- `ai/` - AI integration and model management
  - `chat.py` - OpenAI-compatible API client
  - `selector.py` - Free model selection logic
  - `free_models_scraper.py` - Dynamic model discovery
- `core/` - Shared utilities and data models
  - `config.py` - Configuration handling
  - `models.py` - Data structures
  - `utils.py` - Common utilities
- `infra/` - Infrastructure and cross-cutting concerns
  - `logging.py` - Unified logging system
  - `secure_config.py` - Configuration loading

### Feature Modules
- `scrape/` - News article scraping
  - `runner.py` - Main scraping orchestrator
  - `selectors.py` - Site-specific content selectors
- `process/` - Content processing and translation
  - `engine.py` - Two-stage processing pipeline
- `export/` - Document generation
  - `docx.py` - DOCX formatting and writing

### Service Layer
- `services/` - High-level business logic
  - `processing.py` - Article processing coordination
  - `exporting.py` - Export workflow management
  - `runs.py` - Run directory and caching management
- `tui/` - Terminal user interface
  - `tui.py` - Rich-based interactive interface
- `cli/` - Command-line utilities
  - `common.py` - Shared CLI functions

## Runtime Directories

- `runs/` - Execution artifacts (auto-created)
  - `runs/<timestamp>/` - Per-run directories
    - `scraped.json` - Raw scraped articles
    - `processed.json` - Cleaned and translated content
- `.n2d_cache/` - Persistent caching
  - `crawled.sqlite3` - URL deduplication cache
- `Desktop/英文新闻稿/` - Default export location

## Architecture Principles

- **Layered Design**: Infrastructure → Core → Services → UI
- **Single Responsibility**: Each module has a focused purpose
- **Data Flow**: Clear pipeline from scraping to export
- **Configuration-Driven**: Behavior controlled via `config.yml`
- **Caching Strategy**: Persistent URL cache, per-run artifacts
- **Error Handling**: Unified logging with dual console/file output