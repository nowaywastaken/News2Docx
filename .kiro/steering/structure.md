# Project Structure

## Entry Point

- `index.py`: Main application entry, initializes logging and launches Rich TUI

## Package Organization

The `news2docx/` package follows a layered architecture:

### Core Layer (`core/`)
- `models.py`: Data models (Article, ProcessedArticle, etc.)
- `config.py`: Configuration schemas and validation
- `utils.py`: Shared utilities (timestamps, text processing)

### Infrastructure (`infra/`)
- `logging.py`: Unified logging setup (console + file)
- `secure_config.py`: YAML config loading

### Domain Logic

#### Scraping (`scrape/`)
- `runner.py`: GDELT API integration, concurrent scraping, SQLite caching
- `selectors.py`: Site-specific content selectors (CSS/XPath)

#### AI Processing (`ai/`)
- `chat.py`: OpenAI-compatible API client with retry logic
- `free_models_scraper.py`: Auto-discovery of free SiliconFlow models
- `selector.py`: Model selection strategy (concurrent first-success)

#### Processing (`process/`)
- `engine.py`: Article cleaning, noise removal, paragraph merging

#### Export (`export/`)
- `docx.py`: DOCX generation with formatting (fonts, bold titles, indentation)

### Service Layer (`services/`)
High-level orchestration combining multiple domain components:
- `processing.py`: End-to-end article processing (clean → translate → align)
- `exporting.py`: Export coordination (single file vs per-article)
- `runs.py`: Run directory management

### UI Layer (`tui/`)
- `tui.py`: Rich-based terminal interface (menus, progress bars, health checks)

### CLI Utilities (`cli/`)
- `common.py`: Shared CLI helpers (API key validation, environment setup)

## Configuration Files

- `config.yml`: User-editable runtime configuration
- `pyproject.toml`: Tool configuration (Black, Ruff, pytest, mypy)
- `requirements.txt`: Production dependencies
- `requirements-dev.txt`: Development dependencies

## Data Directories

- `.n2d_cache/`: Scraping cache (SQLite + JSON responses)
- `runs/`: Per-run artifacts (scraped.json, processed.json)
- `assets/`: Static resources (if any)

## Architectural Patterns

- **Separation of concerns**: Clear boundaries between scraping, processing, and export
- **Service orchestration**: High-level services compose lower-level domain logic
- **Configuration-driven**: Behavior controlled via `config.yml` and environment variables
- **Logging-first**: All operations log to both console and file
- **Concurrent execution**: Thread pools for scraping and AI calls
- **Caching**: SQLite-based URL deduplication
