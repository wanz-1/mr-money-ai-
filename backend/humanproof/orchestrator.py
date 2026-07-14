"""Master orchestration engine for HumanProof AI review agents."""

from __future__ import annotations

import uuid
from typing import Dict, Iterable, List

from .analyzers import AGENTS, severity_weight, words
from .models import AgentResult, Document, DocumentMetadata, Finding, ReviewReport, utc_now


DEFAULT_LIMITATIONS = [
    "Local analysis provides decision support, not legal, academic, or publication certification.",
    "Transparent AI-writing analysis is probabilistic and must not be treated as definitive authorship proof.",
    "External source matching, DOI resolution, and live fact verification require configured network services.",
]


def review_text(text: str, filename: str = "untitled.txt") -> ReviewReport:
    metadata = DocumentMetadata(filename=filename, file_format="txt", content_type="text/plain", size_bytes=len(text.encode("utf-8")))
    return review_document(Document(text=text, metadata=metadata))


def review_document(document: Document) -> ReviewReport:
    agent_results: List[AgentResult] = [agent.analyze(document) for agent in AGENTS]
    findings = sorted(
        [finding for result in agent_results for finding in result.findings],
        key=lambda item: severity_weight(item.severity),
        reverse=True,
    )
    scores = _build_scores(agent_results, findings, document)
    limitations = _merge_limitations(document.limitations, agent_results)
    summary = _summary(scores, findings, document)
    action_plan = _action_plan(findings)
    review_id = str(uuid.uuid4())
    created_at = utc_now()
    return ReviewReport(
        review_id=review_id,
        created_at=created_at,
        document=document.metadata,
        summary=summary,
        scores=scores,
        findings=findings,
        agents=agent_results,
        limitations=limitations,
        action_plan=action_plan,
        revision_history=[
            {
                "timestamp": created_at,
                "actor": "HumanProof AI",
                "event": "Initial automated review completed",
            }
        ],
    )


def _merge_limitations(document_limitations: Iterable[str], agent_results: Iterable[AgentResult]) -> List[str]:
    seen = set()
    merged: List[str] = []
    for item in list(document_limitations) + DEFAULT_LIMITATIONS + [limitation for result in agent_results for limitation in result.limitations]:
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _build_scores(agent_results: List[AgentResult], findings: List[Finding], document: Document) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    for result in agent_results:
        metrics.update(result.metrics)

    writing_quality = _average(
        metrics.get("grammar_score"),
        metrics.get("style_score"),
        metrics.get("readability_score"),
        metrics.get("structure_score"),
        metrics.get("tone_score"),
        metrics.get("authorship_consistency_score"),
    )
    citation = metrics.get("citation_score", 100.0 if len(words(document.text)) < 500 else 85.0)
    accessibility = metrics.get("accessibility_score", 100.0)
    compliance = metrics.get("compliance_score", 100.0)
    security = metrics.get("security_score", 100.0)
    fact_check = metrics.get("fact_check_score", 100.0)
    originality = metrics.get("originality_score", 100.0)
    similarity = metrics.get("similarity_score", 0.0)
    grammar = metrics.get("grammar_score", 100.0)
    readability = metrics.get("readability_score", 100.0)

    severe_penalty = sum(severity_weight(item.severity) for item in findings if item.severity in {"high", "critical"})
    publication = _average(writing_quality, citation, accessibility, compliance, security, fact_check, originality) - severe_penalty

    scores: Dict[str, float] = {
        "publication_readiness": _clamp(publication),
        "writing_quality": _clamp(writing_quality),
        "grammar": _clamp(grammar),
        "readability": _clamp(readability),
        "originality": _clamp(originality),
        "similarity": _clamp(similarity),
        "citation": _clamp(citation),
        "accessibility": _clamp(accessibility),
        "compliance": _clamp(compliance),
        "security": _clamp(security),
        "fact_checking": _clamp(fact_check),
        "ai_writing_indicator": _clamp(metrics.get("ai_writing_indicator", 0.0)),
        "ai_analysis_confidence": _clamp(metrics.get("ai_analysis_confidence", 0.0)),
    }
    for key, value in metrics.items():
        scores.setdefault(key, _clamp(value))
    return scores


def _average(*values: float) -> float:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 100.0


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def _summary(scores: Dict[str, float], findings: List[Finding], document: Document) -> str:
    word_count = len(words(document.text))
    high_risk = sum(1 for item in findings if item.severity in {"high", "critical"})
    if high_risk:
        risk = f"{high_risk} high-priority issue(s) require review before publication"
    elif findings:
        risk = f"{len(findings)} improvement opportunity/opportunities found"
    else:
        risk = "no blocking issues found"
    return (
        f"Reviewed {word_count} words from {document.metadata.filename}. "
        f"Publication readiness is {scores['publication_readiness']:.1f}/100; {risk}."
    )


def _action_plan(findings: List[Finding]) -> List[str]:
    if not findings:
        return ["Perform a human final read-through and export the publication report."]
    plan: List[str] = []
    for finding in findings[:8]:
        recommendation = finding.recommendation.rstrip(".")
        item = f"{finding.severity.upper()}: {finding.title} - {recommendation}."
        if item not in plan:
            plan.append(item)
    return plan

