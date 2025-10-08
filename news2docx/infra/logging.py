"""Log4j-aligned logging utilities for the project.

This module provides a centralized, Log4j-like logging system for Python:

- Hierarchical loggers (e.g. ``news2docx.engine.batch``)
- Multiple appenders: console and optional rolling file
- Pattern layout or JSON layout
- Levels aligned with Log4j, including ``TRACE`` (custom) and ``FATAL`` (alias of CRITICAL)
- MDC (Mapped Diagnostic Context) support via ``contextvars``

Configuration via environment variables (prefix: N2D_):
- ``N2D_LOG_LEVEL``: TRACE, DEBUG, INFO, WARN, ERROR, FATAL (default: INFO)
- ``N2D_LOG_JSON``: 1 to enable JSON layout (default: 0)
- Note: local file appenders are disabled by design for security; only console output is enabled.

The helpers below keep backward compatibility for existing call sites
like ``unified_print`` and ``log_task_*``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
import os
import sys
from typing import Any, Dict, Optional

# ---------------- Levels: add TRACE, FATAL alias ----------------

TRACE_LEVEL = 5
if not hasattr(logging, "TRACE"):
    logging.addLevelName(TRACE_LEVEL, "TRACE")


def _trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


if not hasattr(logging.Logger, "trace"):
    logging.Logger.trace = _trace  # type: ignore[attr-defined]

# Provide FATAL as alias to CRITICAL for familiarity
if not hasattr(logging, "FATAL"):
    logging.FATAL = logging.CRITICAL  # type: ignore[attr-defined]


# ---------------- MDC (Mapped Diagnostic Context) ----------------

_MDC: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("MDC", default={})


def mdc_put(key: str, value: Any) -> None:
    d = dict(_MDC.get())
    d[key] = value
    _MDC.set(d)


def mdc_get(key: str, default: Any = None) -> Any:
    return _MDC.get().get(key, default)


def mdc_remove(key: str) -> None:
    d = dict(_MDC.get())
    d.pop(key, None)
    _MDC.set(d)


def mdc_clear() -> None:
    _MDC.set({})


def mdc_copy() -> Dict[str, Any]:
    return dict(_MDC.get())


class MDCFilter(logging.Filter):
    """Inject MDC into LogRecord as dict and compact string."""

    def filter(self, record: logging.LogRecord) -> bool:  # always True
        d = _MDC.get()
        # Attach as dict
        setattr(record, "mdc", d)
        # And compact pair string
        if d:
            parts = []
            for k, v in d.items():
                try:
                    parts.append(f"{k}={v}")
                except Exception:
                    parts.append(f"{k}=<err>")
            mdc_str = " ".join(parts)
            setattr(record, "mdc_str", mdc_str)
            setattr(record, "mdc_suffix", f" | MDC: {mdc_str}")
        else:
            setattr(record, "mdc_str", "")
            setattr(record, "mdc_suffix", "")
        return True


# ---------------- Formatters ----------------


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach MDC if present
        mdc = getattr(record, "mdc", None)
        if isinstance(mdc, dict) and mdc:
            payload["mdc"] = mdc
        # Exception info
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


# ---------------- Utilities ----------------

_CONFIGURED = False
_CACHE: Dict[str, logging.Logger] = {}


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _level_from_env(name: str, default: str = "INFO") -> int:
    s = str(os.getenv(name, default)).strip().upper()
    aliases = {"WARN": "WARNING", "FATAL": "CRITICAL"}
    s = aliases.get(s, s)
    if s == "TRACE":
        return TRACE_LEVEL
    return getattr(logging, s, logging.INFO)


def _default_log_file() -> str:
    # File logging is disabled; keep placeholder for compatibility.
    return ""


def build_logging_config() -> Dict[str, Any]:
    """Build a dictConfig resembling Log4j concepts (appenders/layouts)."""
    json_layout = _env_bool("N2D_LOG_JSON", False)
    level = _level_from_env("N2D_LOG_LEVEL", "INFO")
    # File logging is disabled by default

    fmt = "[%(asctime)s][%(levelname)s][%(name)s] %(message)s%(mdc_suffix)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    formatters: Dict[str, Any] = {
        "pattern": {
            "()": logging.Formatter,
            "format": fmt,
            "datefmt": datefmt,
        },
        "json": {
            "()": JSONFormatter,
        },
    }

    console_formatter = "json" if json_layout else "pattern"
    # file_formatter unused (file handler disabled)

    handlers: Dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
            "formatter": console_formatter,
            "filters": ["mdc"],
            "stream": "ext://sys.stderr",
        }
    }

    # File appender disabled to avoid local file logging

    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "mdc": {
                "()": MDCFilter,
            }
        },
        "formatters": formatters,
        "handlers": handlers,
        "root": {
            "level": level,
            "handlers": ["console"],
        },
        # Named loggers inherit root config; examples for fine-grained control:
        # "loggers": { "news2docx": {"level": level, "handlers": ["console", "file"], "propagate": False} }
    }
    return config


def init_logging(force: bool = False) -> None:
    """Initialize global logging using dictConfig.

    Safe to call multiple times; no-op if already configured unless ``force``.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    # Ensure TRACE is recognized by the root logger
    logging.getLogger("").setLevel(_level_from_env("N2D_LOG_LEVEL", "INFO"))
    logging.config.dictConfig(build_logging_config())
    _CONFIGURED = True


def _ensure_logging():
    global _CONFIGURED
    if not _CONFIGURED and not logging.getLogger("").handlers:
        try:
            init_logging()
        except Exception:
            # Fallback: very basic setup to avoid silent logs
            logging.basicConfig(
                level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s"
            )
            _CONFIGURED = True


def get_unified_logger(program: str, task_type: str) -> logging.Logger:
    """Return a hierarchical logger like ``news2docx.<program>.<task_type>``.

    Handlers are managed at the root; this function ensures logging is initialized.
    """
    _ensure_logging()
    name = f"news2docx.{program}.{task_type}".strip(".")
    if name in _CACHE:
        return _CACHE[name]
    logger = logging.getLogger(name)
    _CACHE[name] = logger
    return logger


def unified_print(message: str, program: str, task_type: str, level: str = "info") -> None:
    """Console echo + logger write, preserving existing behavior.

    Level accepts TRACE/DEBUG/INFO/WARNING/ERROR/FATAL (case-insensitive).
    """
    logger = get_unified_logger(program, task_type)
    formatted = f"[{program}][{task_type}] {message}"
    # Always echo to console for CLI UX
    try:
        print(formatted)
    except Exception:
        pass
    lvl = str(level or "info").strip().lower()
    if lvl == "trace":
        logger.trace(message)  # type: ignore[attr-defined]
    elif lvl in {"fatal", "critical"}:
        logger.critical(message)
    else:
        log_fn = getattr(logger, lvl, logger.info)
        log_fn(message)


def log_task_start(program: str, task_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    logger = get_unified_logger(program, task_type)
    logger.info("[TASK START] %s", json.dumps(details or {}, ensure_ascii=False))


def log_task_end(
    program: str, task_type: str, success: bool, details: Optional[Dict[str, Any]] = None
) -> None:
    logger = get_unified_logger(program, task_type)
    payload = {"success": success}
    if details:
        payload.update(details)
    logger.info("[TASK END] %s", json.dumps(payload, ensure_ascii=False))


def log_processing_step(
    program: str, task_type: str, message: str, details: Optional[Dict[str, Any]] = None
) -> None:
    logger = get_unified_logger(program, task_type)
    if details:
        logger.info("%s | %s", message, json.dumps(details, ensure_ascii=False))
    else:
        logger.info("%s", message)


def log_error(program: str, task_type: str, error: Exception, context: str = "") -> None:
    logger = get_unified_logger(program, task_type)
    if context:
        logger.error("%s | %s", context, error, exc_info=isinstance(error, Exception))
    else:
        logger.error("%s", error, exc_info=isinstance(error, Exception))


def log_performance(
    program: str, task_type: str, metric: str, value: Any, details: Optional[Dict[str, Any]] = None
) -> None:
    logger = get_unified_logger(program, task_type)
    payload = {"metric": metric, "value": value}
    if details:
        payload.update(details)
    logger.info("[PERF] %s", json.dumps(payload, ensure_ascii=False))


def log_processing_result(
    program: str,
    task_type: str,
    message: str,
    input_data: Any,
    output_data: Any,
    status: str = "success",
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    logger = get_unified_logger(program, task_type)
    payload: Dict[str, Any] = {
        "message": message,
        "status": status,
        "input": input_data,
        "output": output_data,
    }
    if metrics:
        payload["metrics"] = metrics
    logger.info("[RESULT] %s", json.dumps(payload, ensure_ascii=False))


def log_article_processing(
    program: str,
    task_type: str,
    article_id: str,
    title: str,
    url: str,
    original_content: str,
    processed_content: str,
    original_word_count: int,
    final_word_count: int,
    duration: float,
    status: str,
    error_msg: str = "",
) -> None:
    logger = get_unified_logger(program, task_type)
    payload: Dict[str, Any] = {
        "article_id": article_id,
        "title": title,
        "url": url,
        "original_word_count": original_word_count,
        "final_word_count": final_word_count,
        "duration": duration,
        "status": status,
    }
    if error_msg:
        payload["error"] = error_msg
    logger.info("[ARTICLE] %s", json.dumps(payload, ensure_ascii=False))


def log_api_call(
    program: str,
    task_type: str,
    api_name: str,
    url: str,
    request_data: Any,
    response_data: Any,
    response_time: float,
    status_code: int,
) -> None:
    logger = get_unified_logger(program, task_type)
    payload = {
        "api": api_name,
        "url": url,
        "request": request_data,
        "response": response_data,
        "response_time": response_time,
        "status_code": status_code,
    }
    logger.info("[API] %s", json.dumps(payload, ensure_ascii=False))


def log_file_operation(
    program: str,
    task_type: str,
    operation: str,
    file_path: str,
    file_size: int,
    duration: float,
    status: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    logger = get_unified_logger(program, task_type)
    payload: Dict[str, Any] = {
        "operation": operation,
        "path": file_path,
        "size": file_size,
        "duration": duration,
        "status": status,
    }
    if extra:
        payload.update(extra)
    logger.info("[FILE] %s", json.dumps(payload, ensure_ascii=False))


def log_batch_processing(
    program: str,
    task_type: str,
    operation: str,
    total_items: int,
    success_count: int,
    failure_count: int,
    duration: float,
    status: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    logger = get_unified_logger(program, task_type)
    payload: Dict[str, Any] = {
        "operation": operation,
        "total": total_items,
        "success": success_count,
        "failed": failure_count,
        "duration": duration,
        "status": status,
    }
    if extra:
        payload.update(extra)
    logger.info("[BATCH] %s", json.dumps(payload, ensure_ascii=False))


__all__ = [
    "init_logging",
    "build_logging_config",
    "mdc_put",
    "mdc_get",
    "mdc_remove",
    "mdc_clear",
    "mdc_copy",
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
