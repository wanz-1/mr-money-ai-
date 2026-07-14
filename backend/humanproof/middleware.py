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


def apply_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
    handler.send_header("Access-Control-Max-Age", "86400")


def apply_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")


def authenticate_request(handler: BaseHTTPRequestHandler) -> Optional[AuthContext]:
    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        return None
    permissions = payload.get("permissions", [])
    return AuthContext(
        user_id=payload.get("sub", ""),
        org_id=payload.get("org_id", ""),
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


def validate_json_body(raw: bytes) -> tuple:
    if not raw or raw == b"{}":
        return {}, None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, "JSON body must be an object."
        return data, None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"Invalid JSON: {exc}"
