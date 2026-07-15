"""Conversation memory system with JSON file-based storage."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import utc_now

_DATA_DIR = Path(__file__).resolve().parent / "data"

CATEGORIES = ("preference", "fact", "project", "conversation", "knowledge")

_DEFAULT_TTL_SECONDS = 86400 * 90


@dataclass
class MemoryEntry:
    id: str
    user_id: str
    category: str
    content: str
    metadata: Dict[str, Any]
    created_at: str
    accessed_at: str
    importance: float
    content_hash: str = ""
    ttl_seconds: int = 0
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConversationMemory:
    """Manages a per-user memory store backed by a JSON file."""

    def __init__(self, user_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self.user_id = user_id
        self._ttl = ttl_seconds
        self._file = _DATA_DIR / f"memory_{user_id}.json"
        self._entries: List[MemoryEntry] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = [e.to_dict() for e in self._entries]
        self._file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._file.exists():
            self._entries = []
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
            self._entries = [MemoryEntry(**item) for item in raw]
        except (json.JSONDecodeError, TypeError):
            self._entries = []

    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()[:16]

    def _is_expired(self, entry: MemoryEntry) -> bool:
        if entry.ttl_seconds <= 0:
            return False
        try:
            created = entry.created_at
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
            return elapsed > entry.ttl_seconds
        except (ValueError, TypeError):
            return False

    def _purge_expired(self) -> None:
        before = len(self._entries)
        self._entries = [e for e in self._entries if not self._is_expired(e)]
        if len(self._entries) < before:
            self._save()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        category: str,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 0.5,
        ttl_seconds: Optional[int] = None,
    ) -> MemoryEntry:
        content_hash = self._compute_hash(content)
        for existing in self._entries:
            if existing.content_hash == content_hash and existing.category == category:
                existing.accessed_at = utc_now()
                existing.importance = max(existing.importance, importance)
                self._save()
                return existing

        now = utc_now()
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            user_id=self.user_id,
            category=category,
            content=content,
            metadata=metadata or {},
            created_at=now,
            accessed_at=now,
            importance=max(0.0, min(1.0, importance)),
            content_hash=content_hash,
            ttl_seconds=ttl,
        )
        self._entries.append(entry)
        self._save()
        return entry

    def update_content(self, entry_id: str, new_content: str) -> bool:
        for entry in self._entries:
            if entry.id == entry_id:
                entry.content = new_content
                entry.content_hash = self._compute_hash(new_content)
                entry.accessed_at = utc_now()
                self._save()
                return True
        return False

    def delete(self, entry_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemoryEntry]:
        self._purge_expired()
        query_words = [w.lower() for w in re.split(r"\W+", query) if w]
        if not query_words:
            return []

        scored: List[tuple[float, MemoryEntry]] = []
        for entry in self._entries:
            if category and entry.category != category:
                continue
            content_words = set(entry.content.lower().split())
            overlap = sum(1 for w in query_words if w in content_words)
            if overlap == 0:
                continue
            score = (overlap / len(query_words)) * entry.importance
            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = [entry for _, entry in scored[:limit]]
        now = utc_now()
        for entry in results:
            entry.accessed_at = now
        if results:
            self._save()
        return results

    def get_recent(self, limit: int = 20) -> List[MemoryEntry]:
        entries = sorted(self._entries, key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def get_important(self, limit: int = 20) -> List[MemoryEntry]:
        entries = sorted(self._entries, key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update_importance(self, entry_id: str, importance: float) -> bool:
        importance = max(0.0, min(1.0, importance))
        for entry in self._entries:
            if entry.id == entry_id:
                entry.importance = importance
                entry.accessed_at = utc_now()
                self._save()
                return True
        return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        counts: Counter = Counter(e.category for e in self._entries)
        return {
            "total": len(self._entries),
            "by_category": dict(counts),
            "avg_importance": (
                sum(e.importance for e in self._entries) / len(self._entries)
                if self._entries
                else 0.0
            ),
        }

    # ------------------------------------------------------------------
    # Auto-extraction
    # ------------------------------------------------------------------

    def auto_extract(self, message: str) -> List[MemoryEntry]:
        extracted: List[MemoryEntry] = []
        lower = message.lower()

        # Preferences: "I prefer ...", "I like ...", "I want ..."
        for pattern, importance in (
            (r"i prefer (.+)", 0.7),
            (r"i like (.+)", 0.6),
            (r"i want (.+)", 0.6),
            (r"i need (.+)", 0.6),
        ):
            match = re.search(pattern, lower)
            if match:
                content = match.group(1).strip().rstrip(".")
                extracted.append(self.add(content, "preference", {"source": "auto_extract"}, importance))

        # Facts: "X is ...", "X was ...", "X are ..."
        fact_match = re.search(r"(?:the |my )?(\w[\w\s]{2,60})\s+(?:is|was|are|were)\s+(.{10,200})", lower)
        if fact_match:
            content = fact_match.group(0).strip().rstrip(".")
            extracted.append(self.add(content, "fact", {"source": "auto_extract"}, 0.5))

        # Projects: "the project ...", "my project ..."
        project_match = re.search(r"(?:the |my )?(project[\w\s]{0,120})", lower)
        if project_match:
            content = project_match.group(0).strip().rstrip(".")
            extracted.append(self.add(content, "project", {"source": "auto_extract"}, 0.5))

        # Knowledge: general knowledge-like statements with proper nouns or technical terms
        knowledge_match = re.search(
            r"(?:^(.{20,200})$)", message.strip()
        )
        if knowledge_match and not extracted:
            words = message.split()
            if len(words) >= 8:
                extracted.append(self.add(message.strip(), "knowledge", {"source": "auto_extract"}, 0.3))

        return extracted
