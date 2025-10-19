# Design Document

## Overview

The News2Docx refactoring will consolidate the current 9-package architecture into 4 focused modules, reducing code complexity while maintaining all functionality. The design eliminates redundant abstraction layers, consolidates utilities, and simplifies the data flow through the scrape → process → export pipeline.

## Architecture

### Current vs. Proposed Structure

**Current (9 packages, 19 files, 4097 LOC):**
```
news2docx/
├── ai/ (3 files) - AI model selection and API calls
├── cli/ (1 file) - Command line utilities  
├── core/ (3 files) - Configuration, models, utilities
├── export/ (1 file) - DOCX generation
├── infra/ (2 files) - Logging and secure config
├── process/ (1 file) - AI processing engine
├── scrape/ (2 files) - News scraping logic
├── services/ (3 files) - Business logic coordination
└── tui/ (2 files) - Rich terminal interface
```

**Proposed (4 modules, ~12 files, ~2800 LOC):**
```
news2docx/
├── core.py - Configuration, models, utilities (consolidated)
├── pipeline.py - Scrape → Process → Export workflow
├── ai.py - AI processing and model management  
└── tui.py - Rich terminal interface
```

### Key Simplifications

1. **Eliminate Services Layer**: The services/ package duplicates core functionality with unnecessary abstraction
2. **Consolidate Infrastructure**: Merge logging, config, and utilities into core.py
3. **Flatten AI Components**: Combine AI model selection, API calls, and processing into ai.py
4. **Streamline Data Models**: Reduce dataclass complexity and eliminate redundant fields
5. **Simplify Import Chains**: Remove circular dependencies and deep import hierarchies

## Components and Interfaces

### 1. Core Module (`core.py`)

**Responsibilities:**
- Configuration loading and validation
- Data models (Article, ScrapeResult, ProcessedArticle)
- Shared utilities (timestamps, file operations, logging setup)
- Environment variable handling

**Key Classes:**
```python
@dataclass
class Article:
    url: str
    title: str
    content: str
    word_count: int = 0

@dataclass  
class ProcessedArticle:
    url: str
    original_title: str
    translated_title: str
    original_content: str
    translated_content: str
    target_language: str = "Chinese"

class Config:
    # Consolidated configuration with validation
    def load(path: str) -> Dict[str, Any]
    def validate() -> bool
```

**Interface:**
- `load_config(path: str) -> Dict[str, Any]`
- `setup_logging(log_file: str) -> None`
- `get_desktop_path() -> Path`

### 2. Pipeline Module (`pipeline.py`)

**Responsibilities:**
- News scraping from GDELT API
- Content extraction and filtering
- DOCX generation and export
- Run directory management

**Key Functions:**
```python
def scrape_news(config: Dict) -> List[Article]
def export_to_docx(articles: List[ProcessedArticle], config: Dict) -> str
def manage_runs(config: Dict) -> Path
```

**Interface:**
- `run_scrape(config: Dict) -> List[Article]`
- `run_export(articles: List[ProcessedArticle], config: Dict) -> str`

### 3. AI Module (`ai.py`)

**Responsibilities:**
- AI model discovery and selection
- Content cleaning and translation
- API communication with SiliconFlow
- Caching and retry logic

**Key Functions:**
```python
def get_available_models() -> List[str]
def clean_content(text: str, config: Dict) -> str  
def translate_content(text: str, target_lang: str) -> str
def process_articles(articles: List[Article], config: Dict) -> List[ProcessedArticle]
```

**Interface:**
- `process_articles(articles: List[Article], config: Dict) -> List[ProcessedArticle]`

### 4. TUI Module (`tui.py`)

**Responsibilities:**
- Rich-based terminal interface
- User interaction and configuration editing
- Progress display and error handling
- Orchestration of pipeline stages

**Interface:**
- `main() -> None` (entry point from index.py)

## Data Models

### Simplified Article Model
```python
@dataclass
class Article:
    url: str
    title: str  
    content: str
    word_count: int = 0
    scraped_at: str = field(default_factory=now_timestamp)
```

### Simplified ProcessedArticle Model  
```python
@dataclass
class ProcessedArticle:
    url: str
    original_title: str
    translated_title: str
    original_content: str
    translated_content: str
    target_language: str = "Chinese"
    processed_at: str = field(default_factory=now_timestamp)
```

## Error Handling

### Consolidated Error Strategy
- Single logging configuration in `core.py`
- Unified exception handling in pipeline stages
- Remove redundant try-catch blocks
- Preserve user-facing error messages in TUI

### Error Flow
1. **Configuration Errors**: Handled in `core.py` with clear user messages
2. **Network Errors**: Handled in `pipeline.py` with retry logic
3. **AI Processing Errors**: Handled in `ai.py` with fallback strategies
4. **Export Errors**: Handled in `pipeline.py` with path validation

## Testing Strategy

### Preserved Test Coverage
- Maintain all existing pytest test cases
- Update import paths to new module structure
- Preserve test data and fixtures
- Ensure identical output validation

### Test Organization
```
tests/
├── test_core.py - Configuration and utilities
├── test_pipeline.py - Scraping and export
├── test_ai.py - AI processing
└── test_tui.py - Interface testing
```

## Migration Strategy

### Phase 1: Core Consolidation
1. Create new `core.py` with consolidated utilities
2. Merge configuration handling from `infra/` and `core/`
3. Simplify data models
4. Update imports in existing modules

### Phase 2: Pipeline Simplification  
1. Create `pipeline.py` combining scrape and export logic
2. Remove services layer abstraction
3. Consolidate run management
4. Update TUI to use new pipeline

### Phase 3: AI Module Consolidation
1. Create `ai.py` combining all AI-related functionality
2. Merge model selection, API calls, and processing
3. Simplify caching and retry logic
4. Remove redundant AI utilities

### Phase 4: Cleanup and Validation
1. Remove old package directories
2. Update all import statements
3. Run full test suite
4. Validate identical functionality

## Performance Considerations

### Maintained Performance
- Preserve concurrent processing in AI module
- Keep existing caching mechanisms
- Maintain parallel scraping capabilities
- Preserve memory-efficient streaming for large articles

### Improved Performance
- Reduced import overhead from simplified structure
- Fewer function call layers in pipeline
- Consolidated configuration loading
- Streamlined error handling paths