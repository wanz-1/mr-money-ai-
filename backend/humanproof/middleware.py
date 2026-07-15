"""HTTP middleware helpers for Mr Money AI."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .auth import decode_token
from .rbac import Permission, has_permission

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

logger = logging.getLogger("humanproof.middleware")


@dataclass
class AuthContext:
    user_id: str = ""
    org_id: str = ""
    permissions: List[str] = field(default_factory=list)


@dataclass
class MiddlewareResult:
    ok: bool = True
    error: str = ""
    status: HTTPStatus = HTTPStatus.OK
    auth_context: AuthContext = field(default_factory=AuthContext)
    request_id: str = ""


def get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = handler.headers.get("X-Real-IP", "")
    if real:
        return real
    return handler.client_address[0] if handler.client_address else "unknown"


_ALLOWED_ORIGINS: List[str] = []
_ORIGIN_LOCK = False


def set_allowed_origins(origins: List[str]) -> None:
    global _ALLOWED_ORIGINS, _ORIGIN_LOCK
    if _ORIGIN_LOCK:
        logger.warning("Attempted to modify CORS origins after lock")
        return
    _ALLOWED_ORIGINS = [o.rstrip("/") for o in origins]


def lock_origins() -> None:
    global _ORIGIN_LOCK
    _ORIGIN_LOCK = True


def apply_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin", "")
    if _ALLOWED_ORIGINS and origin in _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
    elif not _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", "*")
    else:
        handler.send_header("Access-Control-Allow-Origin", "null")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID, X-CSRF-Token")
    handler.send_header("Access-Control-Max-Age", "86400")


def apply_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'; frame-ancestors 'none'"
    )


def generate_request_id() -> str:
    return secrets.token_hex(8)


_CSRF_TOKEN_STORE: Dict[str, float] = {}
_CSRF_MAX_AGE = 3600


def generate_csrf_token(session_id: str = "default") -> str:
    token = secrets.token_hex(32)
    _CSRF_TOKEN_STORE[token] = time.time()
    return token


def validate_csrf_token(token: str) -> bool:
    if not token or token not in _CSRF_TOKEN_STORE:
        return False
    created = _CSRF_TOKEN_STORE.pop(token, 0)
    return (time.time() - created) < _CSRF_MAX_AGE


_MAX_JSON_DEPTH = 10


def _check_json_depth(obj: Any, depth: int = 0) -> bool:
    if depth > _MAX_JSON_DEPTH:
        return False
    if isinstance(obj, dict):
        return all(_check_json_depth(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return all(_check_json_depth(item, depth + 1) for item in obj)
    return True


def authenticate_request(handler: BaseHTTPRequestHandler) -> Optional[AuthContext]:
    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        return None
    permissions = payload.get("perms", [])
    return AuthContext(
        user_id=payload.get("sub", ""),
        org_id=payload.get("org", ""),
        permissions=permissions,
    )


_RATE_LIMITS: Dict[str, List[float]] = {}


def check_rate_limit(key: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    now = time.time()
    if key not in _RATE_LIMITS:
        _RATE_LIMITS[key] = []
    _RATE_LIMITS[key] = [t for t in _RATE_LIMITS[key] if now - t < window_seconds]
    if len(_RATE_LIMITS[key]) >= max_requests:
        return False
    _RATE_LIMITS[key].append(now)
    return True


def run_middleware(
    handler: BaseHTTPRequestHandler,
    require_auth: bool = False,
    required_permission: Optional[Permission] = None,
) -> MiddlewareResult:
    request_id = handler.headers.get("X-Request-ID", "") or generate_request_id()

    ip = get_client_ip(handler)
    if not check_rate_limit(ip):
        return MiddlewareResult(ok=False, error="Rate limit exceeded.", status=HTTPStatus.TOO_MANY_REQUESTS, request_id=request_id)

    auth = authenticate_request(handler)
    if require_auth:
        if not auth:
            return MiddlewareResult(ok=False, error="Authentication required.", status=HTTPStatus.UNAUTHORIZED, request_id=request_id)
        if required_permission and not has_permission(auth.permissions, required_permission):
            return MiddlewareResult(ok=False, error="Insufficient permissions.", status=HTTPStatus.FORBIDDEN, request_id=request_id)
    return MiddlewareResult(ok=True, auth_context=auth or AuthContext(), request_id=request_id)


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:255] if name else "upload.txt"


def validate_json_body(raw: bytes | None) -> tuple:
    if raw is None:
        return None, "Request body too large or missing."
    if not raw or raw == b"{}":
        return {}, None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, "JSON body must be an object."
        if not _check_json_depth(data):
            return None, "JSON body too deeply nested."
        return data, None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"Invalid JSON: {exc}"
