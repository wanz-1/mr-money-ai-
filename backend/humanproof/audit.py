"""Audit logging for Mr Money AI."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

from .models import utc_now


class AuditEvent:
    __slots__ = ("org_id", "actor_id", "action", "resource_type", "resource_id", "ip_address", "user_agent", "metadata", "timestamp")

    def __init__(
        self,
        org_id: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.org_id = org_id
        self.actor_id = actor_id
        self.action = action
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.metadata = metadata or {}
        self.timestamp = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orgId": self.org_id,
            "actorId": self.actor_id,
            "action": self.action,
            "resourceType": self.resource_type,
            "resourceId": self.resource_id,
            "ipAddress": self.ip_address,
            "userAgent": self.user_agent,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class AuditLogger:
    def __init__(self, flush_interval: float = 5.0, batch_size: int = 50) -> None:
        self._buffer: Deque[AuditEvent] = deque()
        self._lock = threading.Lock()
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._running = False
        self._flusher: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True)
        self._flusher.start()

    def stop(self) -> None:
        self._running = False
        self.flush()

    def log(self, event: AuditEvent) -> None:
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._batch_size:
                self._flush()

    def flush(self) -> None:
        with self._lock:
            self._flush()

    def _flush(self) -> None:
        events = list(self._buffer)
        self._buffer.clear()
        if not events:
            return
        self._write_events(events)

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self._flush_interval)
            self.flush()

    def _write_events(self, events: list) -> None:
        try:
            from . import database
            if database.is_available():
                for event in events:
                    database.write_audit_log(
                        org_id=event.org_id,
                        action=event.action,
                        resource_type=event.resource_type,
                        resource_id=event.event_id if hasattr(event, "event_id") else event.resource_id,
                        actor_id=event.actor_id,
                        ip_address=event.ip_address,
                        user_agent=event.user_agent,
                        metadata=event.metadata,
                    )
                return
        except Exception:
            pass

        for event in events:
            line = json.dumps(event.to_dict(), ensure_ascii=True, default=str)
            print(f"[AUDIT] {line}")


_global_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _global_logger
    if _global_logger is None:
        _global_logger = AuditLogger()
    return _global_logger


def init_audit_logger() -> AuditLogger:
    logger = get_audit_logger()
    logger.start()
    return logger


def shutdown_audit_logger() -> None:
    if _global_logger:
        _global_logger.stop()


def audit(
    org_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    event = AuditEvent(
        org_id=org_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata,
    )
    get_audit_logger().log(event)
