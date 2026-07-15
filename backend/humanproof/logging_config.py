"""Structured logging, monitoring, and observability for Mr Money AI.

Provides JSON logging, request correlation IDs, performance timing,
and metrics collection.
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")
_org_id_ctx: ContextVar[str] = ContextVar("org_id", default="")


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_user_context(user_id: str, org_id: str = "") -> None:
    _user_id_ctx.set(user_id)
    _org_id_ctx.set(org_id)


def get_user_id() -> str:
    return _user_id_ctx.get()


def get_org_id() -> str:
    return _org_id_ctx.get()


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            log_entry["requestId"] = request_id
        user_id = get_user_id()
        if user_id:
            log_entry["userId"] = user_id
        org_id = get_org_id()
        if org_id:
            log_entry["orgId"] = org_id
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        extra_fields = getattr(record, "_structured_extra", None)
        if extra_fields:
            log_entry["data"] = extra_fields
        return json.dumps(log_entry, ensure_ascii=True, default=str)


class HumanReadableFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = get_request_id()
        rid = f" [{request_id[:8]}]" if request_id else ""
        return f"{datetime.now().strftime('%H:%M:%S')}{rid} {record.levelname:8s} {record.name}: {record.getMessage()}"


def setup_logging(level: str = "INFO", json_format: Optional[bool] = None) -> None:
    if json_format is None:
        json_format = os.environ.get("HP_LOG_FORMAT", "").lower() == "json"
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(HumanReadableFormatter())
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Performance timing
# ---------------------------------------------------------------------------

class Timer:
    def __init__(self, name: str = "", logger_name: str = "humanproof.perf") -> None:
        self.name = name
        self.logger = logging.getLogger(logger_name)
        self._start: float = 0
        self._elapsed: float = 0
        self.metadata: Dict[str, Any] = {}

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self._elapsed = time.perf_counter() - self._start
        log_data = {"timer": self.name, "elapsed_ms": round(self._elapsed * 1000, 2)}
        log_data.update(self.metadata)
        self.logger.info("%s completed in %.1fms", self.name, self._elapsed * 1000,
                         extra={"_structured_extra": log_data})

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed * 1000


def timed(name: str = "", logger_name: str = "humanproof.perf") -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            timer_name = name or func.__qualname__
            with Timer(timer_name, logger_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Metrics collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __new__(cls) -> MetricsCollector:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._counters: Dict[str, int] = {}
                    cls._instance._timers: Dict[str, List[float]] = {}
                    cls._instance._gauges: Dict[str, float] = {}
        return cls._instance

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def record_time(self, name: str, elapsed_ms: float) -> None:
        with self._lock:
            if name not in self._timers:
                self._timers[name] = []
            self._timers[name].append(elapsed_ms)
            if len(self._timers[name]) > 1000:
                self._timers[name] = self._timers[name][-500:]

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            timer_stats: Dict[str, Dict[str, float]] = {}
            for name, values in self._timers.items():
                if values:
                    timer_stats[name] = {
                        "count": len(values),
                        "avg_ms": round(sum(values) / len(values), 2),
                        "min_ms": round(min(values), 2),
                        "max_ms": round(max(values), 2),
                        "p95_ms": round(sorted(values)[int(len(values) * 0.95)] if len(values) >= 2 else values[-1], 2),
                    }
            return {
                "counters": dict(self._counters),
                "timers": timer_stats,
                "gauges": dict(self._gauges),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._timers.clear()
            self._gauges.clear()


metrics = MetricsCollector()


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------

def begin_request(request_id: Optional[str] = None) -> str:
    rid = request_id or uuid.uuid4().hex[:16]
    set_request_id(rid)
    metrics.increment("requests.total")
    return rid


def end_request(status_code: int = 200, elapsed_ms: float = 0) -> None:
    metrics.increment(f"requests.{status_code}")
    metrics.record_time("requests.duration_ms", elapsed_ms)
    if status_code >= 500:
        metrics.increment("requests.errors_5xx")
    elif status_code >= 400:
        metrics.increment("requests.errors_4xx")
