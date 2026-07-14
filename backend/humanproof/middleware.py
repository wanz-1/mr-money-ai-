"""HTTP middleware helpers for HumanProof AI."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .auth import decode_token
from .rbac import Permission, has_permission

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler


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


def get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = handler.headers.get("X-Real-IP", "")
    if real:
        return real
    return handler.client_address[0] if handler.client_address else "unknown"


_ALLOWED_ORIGINS: List[str] = []


def set_allowed_origins(origins: List[str]) -> None:
    global _ALLOWED_ORIGINS
    _ALLOWED_ORIGINS = [o.rstrip("/") for o in origins]


def apply_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin", "")
    if _ALLOWED_ORIGINS and origin in _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
    elif not _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", "*")
    else:
        handler.send_header("Access-Control-Allow-Origin", "null")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
    handler.send_header("Access-Control-Max-Age", "86400")


def apply_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; frame-ancestors 'none'"
    )


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


def run_middleware(
    handler: BaseHTTPRequestHandler,
    require_auth: bool = False,
    required_permission: Optional[Permission] = None,
) -> MiddlewareResult:
    auth = authenticate_request(handler)
    if require_auth:
        if not auth:
            return MiddlewareResult(ok=False, error="Authentication required.", status=HTTPStatus.UNAUTHORIZED)
        if required_permission and not has_permission(auth.permissions, required_permission):
            return MiddlewareResult(ok=False, error="Insufficient permissions.", status=HTTPStatus.FORBIDDEN)
    return MiddlewareResult(ok=True, auth_context=auth or AuthContext())


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
        return data, None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"Invalid JSON: {exc}"
