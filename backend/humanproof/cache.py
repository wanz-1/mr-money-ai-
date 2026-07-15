"""Caching layer for Mr Money AI.

Provides in-memory LRU cache with TTL, document hash cache,
and review result cache for performance optimization.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Dict, Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    value: V
    created_at: float
    ttl_seconds: float
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class TTLCache(Generic[K, V]):
    """Thread-safe in-memory LRU cache with per-entry TTL."""

    def __init__(self, max_size: int = 500, default_ttl: float = 3600.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._data: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> Optional[V]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._data[key]
                self._misses += 1
                return None
            entry.hits += 1
            self._hits += 1
            self._data.move_to_end(key)
            return entry.value

    def put(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        with self._lock:
            if key in self._data:
                del self._data[key]
            elif len(self._data) >= self._max_size:
                self._data.popitem(last=False)
            self._data[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl_seconds=ttl if ttl is not None else self._default_ttl,
            )

    def invalidate(self, key: K) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            return count

    def purge_expired(self) -> int:
        with self._lock:
            expired_keys = [k for k, v in self._data.items() if v.is_expired]
            for k in expired_keys:
                del self._data[k]
            return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: K) -> bool:
        return self.get(key) is not None


# ---------------------------------------------------------------------------
# Domain-specific caches
# ---------------------------------------------------------------------------

_doc_hash_cache: TTLCache[str, str] = TTLCache(max_size=1000, default_ttl=86400.0)
_review_cache: TTLCache[str, Dict[str, Any]] = TTLCache(max_size=200, default_ttl=1800.0)
_permission_cache: TTLCache[str, list] = TTLCache(max_size=500, default_ttl=300.0)
_api_key_cache: TTLCache[str, Dict[str, Any]] = TTLCache(max_size=200, default_ttl=300.0)


def cache_doc_hash(doc_id: str, content_hash: str) -> None:
    _doc_hash_cache.put(doc_id, content_hash)


def get_cached_doc_hash(doc_id: str) -> Optional[str]:
    return _doc_hash_cache.get(doc_id)


def invalidate_doc_hash(doc_id: str) -> None:
    _doc_hash_cache.invalidate(doc_id)


def cache_review(review_id: str, review_data: Dict[str, Any]) -> None:
    _review_cache.put(review_id, review_data)


def get_cached_review(review_id: str) -> Optional[Dict[str, Any]]:
    return _review_cache.get(review_id)


def invalidate_review(review_id: str) -> None:
    _review_cache.invalidate(review_id)


def cache_permissions(user_id: str, permissions: list) -> None:
    _permission_cache.put(user_id, permissions)


def get_cached_permissions(user_id: str) -> Optional[list]:
    return _permission_cache.get(user_id)


def invalidate_permissions(user_id: Optional[str] = None) -> None:
    if user_id:
        _permission_cache.invalidate(user_id)
    else:
        _permission_cache.clear()


def cache_api_key(key_hash: str, key_data: Dict[str, Any]) -> None:
    _api_key_cache.put(key_hash, key_data)


def get_cached_api_key(key_hash: str) -> Optional[Dict[str, Any]]:
    return _api_key_cache.get(key_hash)


def invalidate_api_key(key_hash: str) -> None:
    _api_key_cache.invalidate(key_hash)


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:32]


def should_reanalyze(doc_id: str, current_hash: str) -> bool:
    cached_hash = _doc_hash_cache.get(doc_id)
    if cached_hash is None:
        return True
    return cached_hash != current_hash


def cache_stats() -> Dict[str, Any]:
    return {
        "doc_hash": _doc_hash_cache.stats(),
        "reviews": _review_cache.stats(),
        "permissions": _permission_cache.stats(),
        "api_keys": _api_key_cache.stats(),
    }


def purge_all_expired() -> int:
    total = 0
    total += _doc_hash_cache.purge_expired()
    total += _review_cache.purge_expired()
    total += _permission_cache.purge_expired()
    total += _api_key_cache.purge_expired()
    return total
