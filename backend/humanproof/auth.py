"""Authentication and authorization for Mr Money AI."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import bcrypt as _bcrypt
except ImportError:
    _bcrypt = None  # type: ignore[assignment]

try:
    import jwt as _jwt
except ImportError:
    _jwt = None  # type: ignore[assignment]

logger = logging.getLogger("humanproof.auth")

JWT_SECRET = os.environ.get("HP_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = int(os.environ.get("HP_JWT_EXPIRY", "3600"))
JWT_REFRESH_EXPIRY_SECONDS = int(os.environ.get("HP_JWT_REFRESH_EXPIRY", "86400"))
JWT_ISSUER = os.environ.get("HP_JWT_ISSUER", "mr-money-ai")

_TOKEN_BLACKLIST: Dict[str, float] = {}
_MAX_BLACKLIST = 10000

_PASSWORD_MIN_LENGTH = 8
_PASSWORD_SPECIAL_CHARS = set("!@#$%^&*()-_=+[]{}|;:',.<>?/`~")


def _is_strong_password(password: str) -> Tuple[bool, str]:
    if len(password) < _PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {_PASSWORD_MIN_LENGTH} characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain an uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain a lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain a digit."
    if not any(c in _PASSWORD_SPECIAL_CHARS for c in password):
        return False, "Password must contain a special character."
    return True, ""


def blacklist_token(token_id: str) -> None:
    _TOKEN_BLACKLIST[token_id] = time.time()
    if len(_TOKEN_BLACKLIST) >= _MAX_BLACKLIST:
        oldest = sorted(_TOKEN_BLACKLIST, key=_TOKEN_BLACKLIST.get)[:_MAX_BLACKLIST // 2]
        for k in oldest:
            _TOKEN_BLACKLIST.pop(k, None)


def is_token_blacklisted(token_id: str) -> bool:
    return token_id in _TOKEN_BLACKLIST


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
        "jti": uuid.uuid4().hex,
        "iss": JWT_ISSUER,
        "aud": org_id,
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
        "jti": uuid.uuid4().hex,
        "iss": JWT_ISSUER,
        "aud": org_id,
    }
    if _jwt is None:
        return _encode_fallback_jwt(payload)
    return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        if _jwt is None:
            payload = _decode_fallback_jwt(token)
        else:
            payload = _jwt.decode(
                token, JWT_SECRET,
                algorithms=[JWT_ALGORITHM],
                options={"verify_aud": False},
            )
        if not payload:
            return None
        token_id = payload.get("jti", "")
        if token_id and is_token_blacklisted(token_id):
            logger.debug("Token %s is blacklisted", token_id)
            return None
        issuer = payload.get("iss", "")
        if issuer and issuer != JWT_ISSUER:
            logger.warning("Token issuer mismatch: expected=%s got=%s", JWT_ISSUER, issuer)
            return None
        return payload
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
    prefix = "mm_"
    raw_key = prefix + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    computed = hashlib.sha256(raw_key.encode()).hexdigest()
    return hmac.compare_digest(computed, key_hash)


# ---------------------------------------------------------------------------
# TOTP MFA (RFC 6238) — stdlib-only implementation
# ---------------------------------------------------------------------------

import struct

def generate_mfa_secret(length: int = 20) -> str:
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _totp_hotp(secret: str, counter: int, digits: int = 6, algo: str = "sha1") -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    msg = struct.pack(">Q", counter)
    if algo == "sha256":
        h = hmac.new(key, msg, hashlib.sha256).digest()
    elif algo == "sha512":
        h = hmac.new(key, msg, hashlib.sha512).digest()
    else:
        h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def generate_mfa_code(secret: str, time_step: int = 30) -> str:
    counter = int(time.time()) // time_step
    return _totp_hotp(secret, counter)


def verify_mfa_code(secret: str, code: str, time_step: int = 30,
                     window: int = 1) -> bool:
    current_counter = int(time.time()) // time_step
    for offset in range(-window, window + 1):
        expected = _totp_hotp(secret, current_counter + offset)
        if hmac.compare_digest(expected, code):
            return True
    return False


def generate_mfa_uri(secret: str, email: str, issuer: str = "Mr Money AI") -> str:
    import urllib.parse as _urllib_parse
    params = _urllib_parse.urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": 6,
        "period": 30,
    })
    return f"otpauth://totp/{_urllib_parse.quote(issuer)}:{_urllib_parse.quote(email)}?{params}"
