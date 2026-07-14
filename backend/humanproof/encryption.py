"""Encryption utilities for HumanProof AI.

Uses HMAC-based encryption for data integrity. For production use with
sensitive data, configure HP_ENCRYPTION_KEY with a stable secret.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Tuple


_ENCRYPTION_KEY = os.environ.get("HP_ENCRYPTION_KEY", "")


def _get_key() -> bytes:
    if _ENCRYPTION_KEY:
        return hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    return hashlib.sha256(secrets.token_bytes(32)).digest()


def encrypt_data(plaintext: bytes, key: bytes | None = None) -> bytes:
    """Encrypt data using XOR with HMAC-derived keystream + HMAC for integrity."""
    key = key or _get_key()
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
    """Backward-compatible alias."""
    return encrypt_data(plaintext, key)


def decrypt_aes_ctr(ciphertext: bytes, key: bytes | None = None) -> bytes:
    """Backward-compatible alias."""
    return decrypt_data(ciphertext, key)


def hash_document(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_api_key_pair() -> Tuple[str, str]:
    prefix = "hp_"
    raw_key = prefix + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    computed = hashlib.sha256(raw_key.encode()).hexdigest()
    return hmac.compare_digest(computed, key_hash)
