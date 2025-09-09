"""Thin wrapper to reuse existing unified_logger in a package path.

Phase 2 keeps the original module to avoid breaking imports, while
new code can import from `news2docx.infra.logging` for clarity.
"""

from typing import Any, Dict, Optional

# Re-export from the existing unified_logger module
from unified_logger import (
    get_unified_logger,
    unified_print,
    log_task_start,
    log_task_end,
    log_processing_step,
    log_error,
    log_performance,
    log_processing_result,
    log_article_processing,
    log_api_call,
    log_file_operation,
    log_batch_processing,
)

__all__ = [
    "get_unified_logger",
    "unified_print",
    "log_task_start",
    "log_task_end",
    "log_processing_step",
    "log_error",
    "log_performance",
    "log_processing_result",
    "log_article_processing",
    "log_api_call",
    "log_file_operation",
    "log_batch_processing",
]

