"""Knowledge base management for Mr Money AI.

Provides document chunking, keyword extraction, TTL caching,
and search over knowledge-base entries.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


_STOP_WORDS: Set[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "dare", "ought", "used", "it", "its", "he", "she", "they", "them",
    "we", "you", "i", "me", "my", "your", "his", "her", "our", "their",
    "this", "that", "these", "those", "am", "not", "no", "nor", "if",
    "then", "else", "when", "where", "how", "what", "which", "who",
    "whom", "whose", "while", "during", "before", "after", "above",
    "below", "between", "into", "through", "about", "against", "all",
    "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "than", "too", "very", "so", "also", "just", "over",
})


@dataclass
class KnowledgeEntry:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    org_id: str = ""
    title: str = ""
    content: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    chunk_count: int = 0

    def __post_init__(self) -> None:
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()[:32]
        if self.content and not self.chunk_count:
            self.chunk_count = max(1, len(self.content) // 500 + 1)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return False


@dataclass
class KnowledgeChunk:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    entry_id: str = ""
    index: int = 0
    text: str = ""
    keywords: List[str] = field(default_factory=list)
    token_count: int = 0

    def __post_init__(self) -> None:
        if not self.token_count:
            self.token_count = len(self.text.split())


@dataclass
class SearchResult:
    entry_id: str = ""
    chunk_id: str = ""
    score: float = 0.0
    text: str = ""
    title: str = ""
    category: str = ""


def extract_keywords(text: str, top_n: int = 10) -> List[str]:
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(top_n)]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks: List[str] = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + chunk_size]
        chunks.append(" ".join(chunk_words))
        i += chunk_size - overlap
    return chunks


class KnowledgeBase:
    def __init__(self, default_ttl_seconds: int = 2592000) -> None:
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._chunks: Dict[str, KnowledgeChunk] = {}
        self._entry_chunks: Dict[str, List[str]] = {}
        self._default_ttl = default_ttl_seconds

    def add_entry(self, org_id: str, title: str, content: str,
                  category: str = "general", tags: Optional[List[str]] = None,
                  ttl_seconds: Optional[int] = None,
                  metadata: Optional[Dict[str, Any]] = None) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            org_id=org_id,
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            metadata=metadata or {},
        )
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        if ttl > 0:
            from datetime import timedelta
            exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            entry.expires_at = exp.isoformat()

        self._entries[entry.id] = entry
        chunk_ids: List[str] = []
        texts = chunk_text(content)
        for idx, text in enumerate(texts):
            chunk = KnowledgeChunk(
                entry_id=entry.id,
                index=idx,
                text=text,
                keywords=extract_keywords(text),
            )
            self._chunks[chunk.id] = chunk
            chunk_ids.append(chunk.id)
        self._entry_chunks[entry.id] = chunk_ids
        entry.chunk_count = len(chunk_ids)
        return entry

    def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        entry = self._entries.get(entry_id)
        if entry and entry.is_expired():
            self.delete_entry(entry_id)
            return None
        return entry

    def list_entries(self, org_id: str, category: Optional[str] = None) -> List[KnowledgeEntry]:
        entries = [e for e in self._entries.values()
                   if e.org_id == org_id and not e.is_expired()]
        if category:
            entries = [e for e in entries if e.category == category]
        return entries

    def update_entry(self, entry_id: str, title: Optional[str] = None,
                     content: Optional[str] = None,
                     tags: Optional[List[str]] = None) -> bool:
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        if title is not None:
            entry.title = title
        if content is not None:
            for cid in self._entry_chunks.get(entry_id, []):
                self._chunks.pop(cid, None)
            entry.content = content
            entry.content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            texts = chunk_text(content)
            chunk_ids: List[str] = []
            for idx, text in enumerate(texts):
                chunk = KnowledgeChunk(
                    entry_id=entry_id,
                    index=idx,
                    text=text,
                    keywords=extract_keywords(text),
                )
                self._chunks[chunk.id] = chunk
                chunk_ids.append(chunk.id)
            self._entry_chunks[entry_id] = chunk_ids
            entry.chunk_count = len(chunk_ids)
        if tags is not None:
            entry.tags = tags
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def delete_entry(self, entry_id: str) -> bool:
        entry = self._entries.pop(entry_id, None)
        if not entry:
            return False
        for cid in self._entry_chunks.pop(entry_id, []):
            self._chunks.pop(cid, None)
        return True

    def search(self, org_id: str, query: str, top_k: int = 5) -> List[SearchResult]:
        query_keywords = set(extract_keywords(query))
        if not query_keywords:
            query_words = set(query.lower().split())
        else:
            query_words = query_keywords

        scores: List[SearchResult] = []
        for chunk in self._chunks.values():
            entry = self._entries.get(chunk.entry_id)
            if not entry or entry.org_id != org_id or entry.is_expired():
                continue
            chunk_words = set(chunk.keywords)
            overlap = query_words & chunk_words
            if not overlap:
                chunk_text_words = set(chunk.text.lower().split())
                overlap = query_words & chunk_text_words
            if overlap:
                score = len(overlap) / max(len(query_words), 1)
                scores.append(SearchResult(
                    entry_id=chunk.entry_id,
                    chunk_id=chunk.id,
                    score=score,
                    text=chunk.text,
                    title=entry.title,
                    category=entry.category,
                ))

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]

    def purge_expired(self) -> int:
        expired_ids = [eid for eid, e in self._entries.items() if e.is_expired()]
        for eid in expired_ids:
            self.delete_entry(eid)
        return len(expired_ids)

    def stats(self, org_id: str) -> Dict[str, Any]:
        entries = [e for e in self._entries.values() if e.org_id == org_id]
        chunk_count = 0
        for e in entries:
            chunk_count += len(self._entry_chunks.get(e.id, []))
        categories: Dict[str, int] = {}
        for e in entries:
            categories[e.category] = categories.get(e.category, 0) + 1
        return {
            "total_entries": len(entries),
            "total_chunks": chunk_count,
            "categories": categories,
        }
