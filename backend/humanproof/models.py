"""Shared domain models for Mr Money AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VALID_SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})
VALID_SCORE_KEYS = frozenset({
    "publication_readiness", "writing_quality", "grammar", "readability",
    "originality", "ai_writing_indicator", "citation_quality",
    "argument_strength", "vocabulary_richness", "sentence_variety",
    "paragraph_balance", "tone_consistency", "structural_quality",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class TextSpan:
    start: Optional[int] = None
    end: Optional[int] = None
    excerpt: str = ""

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None:
            if self.start > self.end:
                raise ValueError(f"TextSpan start ({self.start}) > end ({self.end})")


@dataclass
class DocumentMetadata:
    filename: str = "untitled.txt"
    file_format: str = "txt"
    content_type: str = "text/plain"
    size_bytes: int = 0
    extracted_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be >= 0, got {self.size_bytes}")


@dataclass
class Document:
    text: str
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    limitations: List[str] = field(default_factory=list)


@dataclass
class Finding:
    category: str
    severity: str
    title: str
    message: str
    recommendation: str
    confidence: float
    agent: str
    span: Optional[TextSpan] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.severity = self.severity.lower() if self.severity else "info"
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {VALID_SEVERITIES}, got {self.severity!r}")
        self.confidence = _clamp(self.confidence, 0.0, 1.0)
        if not self.category:
            raise ValueError("category must not be empty")
        if not self.agent:
            raise ValueError("agent must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.span is None:
            payload["span"] = None
        return payload


@dataclass
class AgentResult:
    agent: str
    summary: str
    metrics: Dict[str, float] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("agent must not be empty")
        for key in self.metrics:
            self.metrics[key] = _clamp(self.metrics[key], 0.0, 100.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "metrics": self.metrics,
            "findings": [finding.to_dict() for finding in self.findings],
            "limitations": self.limitations,
        }


@dataclass
class ReviewReport:
    review_id: str
    created_at: str
    document: DocumentMetadata
    summary: str
    scores: Dict[str, float]
    findings: List[Finding]
    agents: List[AgentResult]
    limitations: List[str]
    action_plan: List[str]
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    score_explanations: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, val in self.scores.items():
            self.scores[key] = _clamp(val, 0.0, 100.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewId": self.review_id,
            "createdAt": self.created_at,
            "document": asdict(self.document),
            "summary": self.summary,
            "scores": self.scores,
            "scoreExplanations": self.score_explanations,
            "findings": [finding.to_dict() for finding in self.findings],
            "agents": [agent.to_dict() for agent in self.agents],
            "limitations": self.limitations,
            "actionPlan": self.action_plan,
            "revisionHistory": self.revision_history,
        }
