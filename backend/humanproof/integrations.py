"""Third-party integration connection manager for Mr Money AI.

Provides OAuth2 flows, webhook HMAC signing, retry logic,
and circuit-breaker patterns for external services.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


class IntegrationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    EXPIRED = "expired"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class IntegrationConnection:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    org_id: str = ""
    provider: str = ""
    name: str = ""
    status: IntegrationStatus = IntegrationStatus.ACTIVE
    access_token_ref: str = ""
    refresh_token_ref: str = ""
    token_expires_at: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_expired(self) -> bool:
        if self.token_expires_at is None:
            return False
        try:
            exp = datetime.fromisoformat(self.token_expires_at)
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return False


@dataclass
class WebhookSignature:
    secret: str = ""
    timestamp: str = ""
    signature: str = ""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True
        return False

    def reset(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED


def generate_hmac_signature(payload: bytes, secret: str,
                             timestamp: Optional[str] = None) -> WebhookSignature:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    message = f"{ts}.{payload.decode('utf-8', errors='replace')}"
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return WebhookSignature(secret=secret, timestamp=ts, signature=sig)


def verify_hmac_signature(payload: bytes, signature: WebhookSignature,
                           tolerance_seconds: int = 300) -> bool:
    try:
        ts_time = datetime.fromisoformat(signature.timestamp)
        age = (datetime.now(timezone.utc) - ts_time).total_seconds()
        if age > tolerance_seconds:
            return False
    except (ValueError, TypeError):
        return False
    expected = generate_hmac_signature(payload, signature.secret, signature.timestamp)
    return hmac.compare_digest(expected.signature, signature.signature)


class IntegrationManager:
    def __init__(self) -> None:
        self._connections: Dict[str, IntegrationConnection] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    def connect(self, org_id: str, provider: str, name: str,
                config: Optional[Dict[str, Any]] = None) -> IntegrationConnection:
        conn = IntegrationConnection(
            org_id=org_id,
            provider=provider,
            name=name,
            config=config or {},
        )
        self._connections[conn.id] = conn
        self._circuit_breakers[conn.id] = CircuitBreaker()
        return conn

    def disconnect(self, connection_id: str) -> bool:
        conn = self._connections.pop(connection_id, None)
        self._circuit_breakers.pop(connection_id, None)
        if conn:
            conn.status = IntegrationStatus.INACTIVE
            return True
        return False

    def get_connection(self, connection_id: str) -> Optional[IntegrationConnection]:
        return self._connections.get(connection_id)

    def list_connections(self, org_id: str) -> List[IntegrationConnection]:
        return [c for c in self._connections.values() if c.org_id == org_id]

    def send_request(self, connection_id: str, url: str,
                     method: str = "GET", body: Optional[bytes] = None,
                     headers: Optional[Dict[str, str]] = None,
                     timeout: float = 30.0) -> Dict[str, Any]:
        conn = self._connections.get(connection_id)
        if not conn:
            return {"error": "connection_not_found", "status": 0}

        cb = self._circuit_breakers.get(connection_id)
        if cb and not cb.allow_request():
            return {"error": "circuit_open", "status": 0,
                    "retry_after": cb.recovery_timeout}

        hdrs = dict(headers or {})
        if conn.access_token_ref:
            hdrs["Authorization"] = f"Bearer {conn.access_token_ref}"

        req = Request(url, data=body, headers=hdrs, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if cb:
                    cb.record_success()
                return {
                    "status": resp.status,
                    "body": data.decode("utf-8", errors="replace"),
                    "headers": dict(resp.headers),
                }
        except (URLError, OSError, TimeoutError) as exc:
            if cb:
                cb.record_failure()
            return {"error": str(exc), "status": 0}

    def exchange_code(self, connection_id: str, code: str,
                      token_url: str, client_id: str,
                      client_secret: str, redirect_uri: str) -> Dict[str, Any]:
        conn = self._connections.get(connection_id)
        if not conn:
            return {"error": "connection_not_found"}

        body = json.dumps({
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }).encode()

        result = self.send_request(
            connection_id, token_url, method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )

        if "error" not in result and result.get("status", 0) == 200:
            try:
                token_data = json.loads(result["body"])
                conn.access_token_ref = token_data.get("access_token", "")
                conn.refresh_token_ref = token_data.get("refresh_token", "")
                conn.status = IntegrationStatus.ACTIVE
                conn.updated_at = datetime.now(timezone.utc).isoformat()
                if "expires_in" in token_data:
                    from datetime import timedelta
                    exp = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
                    conn.token_expires_at = exp.isoformat()
            except (json.JSONDecodeError, KeyError):
                return {"error": "invalid_token_response"}

        return {"status": "connected" if conn.access_token_ref else "failed"}

    def refresh_token(self, connection_id: str, token_url: str,
                      client_id: str, client_secret: str) -> Dict[str, Any]:
        conn = self._connections.get(connection_id)
        if not conn or not conn.refresh_token_ref:
            return {"error": "no_refresh_token"}

        body = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": conn.refresh_token_ref,
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()

        result = self.send_request(
            connection_id, token_url, method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )

        if "error" not in result and result.get("status", 0) == 200:
            try:
                token_data = json.loads(result["body"])
                conn.access_token_ref = token_data.get("access_token", conn.access_token_ref)
                conn.refresh_token_ref = token_data.get("refresh_token", conn.refresh_token_ref)
                conn.updated_at = datetime.now(timezone.utc).isoformat()
                if "expires_in" in token_data:
                    from datetime import timedelta
                    exp = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
                    conn.token_expires_at = exp.isoformat()
                return {"status": "refreshed"}
            except (json.JSONDecodeError, KeyError):
                return {"error": "invalid_token_response"}

        return {"error": result.get("error", "refresh_failed")}

    def get_circuit_state(self, connection_id: str) -> str:
        cb = self._circuit_breakers.get(connection_id)
        return cb.state.value if cb else "unknown"
