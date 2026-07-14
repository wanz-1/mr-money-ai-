"""Authentication and authorization for Mr Money AI."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import bcrypt as _bcrypt
except ImportError:
    _bcrypt = None  # type: ignore[assignment]

try:
    import jwt as _jwt
except ImportError:
    _jwt = None  # type: ignore[assignment]


JWT_SECRET = os.environ.get("HP_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = int(os.environ.get("HP_JWT_EXPIRY", "3600"))
JWT_REFRESH_EXPIRY_SECONDS = int(os.environ.get("HP_JWT_REFRESH_EXPIRY", "86400"))

if not JWT_SECRET:
    import logging as _log
    _log.warning(
        "HP_JWT_SECRET is not set. Generating a random secret. "
        "All tokens will be invalidated on restart. "
        "Set HP_JWT_SECRET in your environment for stable tokens."
    )
    JWT_SECRET = secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    if _bcrypt is None:
        salt = hashlib.sha256(os.urandom(16)).hexdigest().encode()
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex() + ":" + salt.decode()
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if _bcrypt is None:
        if ":" not in password_hash:
            return False
        stored_hash, salt = password_hash.rsplit(":", 1)
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
        return hmac.compare_digest(computed, stored_hash)
    return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: str,
    org_id: str,
    permissions: List[str],
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org": org_id,
        "perms": permissions,
        "type": "access",
        "iat": now,
        "exp": now + JWT_EXPIRY_SECONDS,
    }
    if extra:
        payload.update(extra)
    if _jwt is None:
        return _encode_fallback_jwt(payload)
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, org_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org": org_id,
        "type": "refresh",
        "iat": now,
        "exp": now + JWT_REFRESH_EXPIRY_SECONDS,
    }
    if _jwt is None:
        return _encode_fallback_jwt(payload)
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        if _jwt is None:
            return _decode_fallback_jwt(token)
        return _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def extract_user_id(token: str) -> Optional[str]:
    payload = decode_token(token)
    if payload and payload.get("type") == "access":
        return payload.get("sub")
    return None


def extract_org_id(token: str) -> Optional[str]:
    payload = decode_token(token)
    return payload.get("org") if payload else None


def extract_permissions(token: str) -> List[str]:
    payload = decode_token(token)
    if payload:
        return payload.get("perms", [])
    return []


# ---------------------------------------------------------------------------
# Fallback JWT encoder/decoder (no PyJWT dependency)
# ---------------------------------------------------------------------------

import base64
import json


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _encode_fallback_jwt(payload: Dict[str, Any]) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload, default=str).encode())
    signing_input = f"{header}.{body}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(signature)}"


def _decode_fallback_jwt(token: str) -> Optional[Dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, body_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{body_b64}".encode()
    expected_sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    payload = json.loads(_b64url_decode(body_b64))
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

def refresh_access_token(refresh_token: str, permissions: List[str]) -> Optional[str]:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        return None
    return create_access_token(
        user_id=payload["sub"],
        org_id=payload["org"],
        permissions=permissions,
    )


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

def generate_api_key() -> Tuple[str, str]:
    prefix = "hp_"
    raw_key = prefix + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    computed = hashlib.sha256(raw_key.encode()).hexdigest()
    return hmac.compare_digest(computed, key_hash)
