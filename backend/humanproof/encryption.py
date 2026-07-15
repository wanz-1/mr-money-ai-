"""Encryption utilities for Mr Money AI.

Uses AES-GCM (via the cryptography library) when available, with HMAC-based
XOR fallback for zero-dependency deployments. Configure HP_ENCRYPTION_KEY
with a stable secret in production.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Tuple

logger = logging.getLogger("humanproof.encryption")

_ENCRYPTION_KEY = os.environ.get("HP_ENCRYPTION_KEY", "")
_IS_PROD = os.environ.get("HP_PROD", "").lower() in ("1", "true", "yes")


def _get_key() -> bytes:
    if _ENCRYPTION_KEY:
        return hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    if _IS_PROD:
        raise RuntimeError("HP_ENCRYPTION_KEY must be set in production")
    logger.warning("No HP_ENCRYPTION_KEY set; generating ephemeral key (data will not survive restart)")
    return hashlib.sha256(secrets.token_bytes(32)).digest()


def _try_aes_gcm(plaintext: bytes, key: bytes) -> bytes | None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes_key = hashlib.sha256(key).digest()[:32]
        nonce = os.urandom(12)
        ct = AESGCM(aes_key).encrypt(nonce, plaintext, None)
        return b"\x01" + nonce + ct
    except ImportError:
        return None


def _try_aes_gcm_decrypt(ciphertext: bytes, key: bytes) -> bytes | None:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if ciphertext[0:1] != b"\x01":
            return None
        aes_key = hashlib.sha256(key).digest()[:32]
        nonce = ciphertext[1:13]
        ct = ciphertext[13:]
        return AESGCM(aes_key).decrypt(nonce, ct, None)
    except ImportError:
        return None


def encrypt_data(plaintext: bytes, key: bytes | None = None) -> bytes:
    """Encrypt data using AES-GCM (preferred) or XOR+HMAC fallback."""
    key = key or _get_key()
    gcm = _try_aes_gcm(plaintext, key)
    if gcm is not None:
        return gcm
    nonce = os.urandom(16)
    keystone = hashlib.sha256(key + nonce).digest()
    encrypted = bytearray()
    counter = 0
    for i in range(0, len(plaintext), 32):
        block = plaintext[i:i + 32]
        ks = hashlib.sha256(keystone + counter.to_bytes(4, "big")).digest()
        encrypted.extend(bytes(a ^ b for a, b in zip(block, ks[:len(block)])))
        counter += 1
    ciphertext = nonce + bytes(encrypted)
    mac = hmac.new(key, ciphertext, hashlib.sha256).digest()
    return ciphertext + mac


def decrypt_data(ciphertext: bytes, key: bytes | None = None) -> bytes:
    """Decrypt and verify integrity."""
    key = key or _get_key()
    gcm = _try_aes_gcm_decrypt(ciphertext, key)
    if gcm is not None:
        return gcm
    if len(ciphertext) < 48:
        raise ValueError("Ciphertext too short")
    mac = ciphertext[-32:]
    data = ciphertext[:-32]
    expected_mac = hmac.new(key, data, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("Data integrity check failed")
    nonce = data[:16]
    encrypted = data[16:]
    keystone = hashlib.sha256(key + nonce).digest()
    decrypted = bytearray()
    counter = 0
    for i in range(0, len(encrypted), 32):
        block = encrypted[i:i + 32]
        ks = hashlib.sha256(keystone + counter.to_bytes(4, "big")).digest()
        decrypted.extend(bytes(a ^ b for a, b in zip(block, ks[:len(block)])))
        counter += 1
    return bytes(decrypted)


def encrypt_aes_ctr(plaintext: bytes, key: bytes | None = None) -> bytes:
    """Backward-compatible alias (now uses AES-GCM when available)."""
    return encrypt_data(plaintext, key)


def decrypt_aes_ctr(ciphertext: bytes, key: bytes | None = None) -> bytes:
    """Backward-compatible alias (now uses AES-GCM when available)."""
    return decrypt_data(ciphertext, key)


def hash_document(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
