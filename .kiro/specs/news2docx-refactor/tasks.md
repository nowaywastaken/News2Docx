# Implementation Plan

- [ ] 1. Create consolidated core module
  - Create new `news2docx/core.py` with unified configuration, models, and utilities
  - Consolidate configuration loading from `infra/secure_config.py` and `core/config.py`
  - Merge data models from `core/models.py` and `process/engine.py` Article class
  - Integrate logging setup from `infra/logging.py`
  - Add shared utilities from `core/utils.py`
  - _Requirements: 1.1, 1.3, 3.3, 4.4_

- [ ] 2. Build unified pipeline module
  - Create `news2docx/pipeline.py` combining scraping and export functionality
  - Integrate scraping logic from `scrape/runner.py` and `scrape/selectors.py`
  - Merge export functionality from `export/docx.py`
  - Consolidate run management from `services/runs.py`
  - Remove services layer abstraction by integrating `services/exporting.py` logic
  - _Requirements: 1.1, 1.2, 3.1, 3.4_

- [ ] 3. Consolidate AI processing module
  - Create `news2docx/ai.py` combining all AI-related functionality
  - Merge AI model selection from `ai/selector.py` and `ai/free_models_scraper.py`
  - Integrate API communication from `ai/chat.py`
  - Consolidate processing logic from `process/engine.py`
  - Remove services abstraction by integrating `services/processing.py`
  - Simplify caching and retry mechanisms
  - _Requirements: 1.1, 1.3, 2.2, 3.1_

- [ ] 4. Streamline TUI interface
  - Update `news2docx/tui.py` to use new consolidated modules
  - Remove dependency on services layer
  - Update import statements to use new module structure
  - Preserve all existing TUI functionality and user interactions
  - _Requirements: 2.5, 5.2_

- [ ] 5. Update main entry point
  - Modify `index.py` to use new module structure
  - Update import statements and function calls
  - Preserve single entry point behavior
  - Maintain all existing command-line compatibility
  - _Requirements: 1.4, 5.2_

- [ ] 6. Remove obsolete package structure
  - Delete old package directories: `ai/`, `cli/`, `core/`, `export/`, `infra/`, `process/`, `scrape/`, `services/`
  - Clean up `__pycache__` directories
  - Remove unused import statements and dead code
  - _Requirements: 1.2, 4.2_

- [ ] 7. Update test suite
  - Modify test imports to use new module structure
  - Update test file organization to match new architecture
  - Ensure all existing test cases pass with new structure
  - Validate identical functionality and output
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 7.1 Create comprehensive integration tests
  - Write end-to-end tests for complete pipeline workflow
  - Test configuration compatibility with existing files
  - Validate output file format and content preservation
  - _Requirements: 5.1, 5.3_

- [ ] 8. Validate refactoring success
  - Run full application test to ensure identical functionality
  - Verify code line count reduction of at least 30%
  - Confirm all configuration options work unchanged
  - Test with existing `config.yml` files for backward compatibility
  - _Requirements: 1.2, 2.1, 5.1_

- [ ] 8.1 Performance benchmarking
  - Compare processing speed before and after refactoring
  - Measure memory usage improvements
  - Validate concurrent processing performance
  - _Requirements: 2.1, 2.2_

- [ ] 9. Update documentation and dependencies
  - Update any internal documentation references
  - Verify all dependencies in `requirements.txt` are still needed
  - Update development tool configurations if needed
  - Ensure `pyproject.toml` settings work with new structure
  - _Requirements: 4.5, 5.4_