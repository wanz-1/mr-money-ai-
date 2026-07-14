"""Shared domain models for HumanProof AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    """Return a compact UTC timestamp suitable for API responses."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class TextSpan:
    start: Optional[int] = None
    end: Optional[int] = None
    excerpt: str = ""


@dataclass
class DocumentMetadata:
    filename: str = "untitled.txt"
    file_format: str = "txt"
    content_type: str = "text/plain"
    size_bytes: int = 0
    extracted_at: str = field(default_factory=utc_now)


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

