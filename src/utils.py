"""Utility functions: logging, retry decorator, atomic JSON I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


# ---- Logging ----

def setup_logging(log_level: str = "INFO", log_file: str | None = None) -> None:
    """Configure logging with timestamps and module names."""
    fmt = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, log_level.upper()), format=fmt, datefmt=datefmt, handlers=handlers)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ---- Retry with exponential backoff ----

def retry_with_backoff(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    jitter: bool = True,
) -> Callable:
    """Decorator: retry on failure with exponential backoff and optional jitter."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(f"All {max_retries} retries exhausted for {func.__name__}: {e}")
                        raise
                    delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
                    if jitter:
                        delay *= random.uniform(0.8, 1.2)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. Retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
            raise last_exception  # type: ignore

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(f"All {max_retries} retries exhausted for {func.__name__}: {e}")
                        raise
                    delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
                    if jitter:
                        delay *= random.uniform(0.8, 1.2)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. Retrying in {delay:.1f}s")
                    time.sleep(delay)
            raise last_exception  # type: ignore

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


# ---- JSON I/O ----

def save_json(data, path: str) -> None:
    """Atomic JSON save: write to temp file, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path: str):
    """Load JSON file. Returns None if missing, empty list if file is empty."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: str) -> list[dict]:
    """Load JSONL file into list of dicts."""
    p = Path(path)
    if not p.exists():
        return []
    results = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def append_jsonl(obj: dict, path: str) -> None:
    """Append a single JSON object as one line to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
