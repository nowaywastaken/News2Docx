"""Package-local unified logging utilities.

Provides a consistent API without depending on a root-level module.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

_CACHE: Dict[str, logging.Logger] = {}


def get_unified_logger(program: str, task_type: str) -> logging.Logger:
    name = f"{program}.{task_type}"
    if name in _CACHE:
        return _CACHE[name]
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s][%(name)s][%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _CACHE[name] = logger
    return logger


def unified_print(message: str, program: str, task_type: str, level: str = "info") -> None:
    logger = get_unified_logger(program, task_type)
    formatted = f"[{program}][{task_type}] {message}"
    print(formatted)
    log_fn = getattr(logger, level.lower(), logger.info)
    log_fn(message)


def log_task_start(program: str, task_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    logger = get_unified_logger(program, task_type)
    logger.info("[TASK START] %s", json.dumps(details or {}, ensure_ascii=False))


def log_task_end(program: str, task_type: str, success: bool, details: Optional[Dict[str, Any]] = None) -> None:
    logger = get_unified_logger(program, task_type)
    payload = {"success": success}
    if details:
        payload.update(details)
    logger.info("[TASK END] %s", json.dumps(payload, ensure_ascii=False))


def log_processing_step(program: str, task_type: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
    logger = get_unified_logger(program, task_type)
    if details:
        logger.info("%s | %s", message, json.dumps(details, ensure_ascii=False))
    else:
        logger.info("%s", message)


def log_error(program: str, task_type: str, error: Exception, context: str = "") -> None:
    logger = get_unified_logger(program, task_type)
    if context:
        logger.error("%s | %s", context, error)
    else:
        logger.error("%s", error)


def log_performance(program: str, task_type: str, metric: str, value: Any, details: Optional[Dict[str, Any]] = None) -> None:
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
