"""Master orchestration engine for Mr Money AI review agents.

Supports pipeline state machine, parallel agent execution,
progress callbacks, and partial results on failure.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional

from .analyzers import AGENTS, severity_weight, words
from .models import AgentResult, Document, DocumentMetadata, Finding, ReviewReport, utc_now


DEFAULT_LIMITATIONS = [
    "Local analysis provides decision support, not legal, academic, or publication certification.",
    "Transparent AI-writing analysis is probabilistic and must not be treated as definitive authorship proof.",
    "External source matching, DOI resolution, and live fact verification require configured network services.",
]


class PipelineState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    PARTIAL = "partial"


class ReviewPipeline:
    """State-machine pipeline for document review."""

    def __init__(self, document: Document, max_workers: int = 4,
                 progress_callback: Optional[Callable[[str, int, int, str], None]] = None) -> None:
        self.document = document
        self.state = PipelineState.PENDING
        self.max_workers = max_workers
        self._progress_cb = progress_callback
        self.agent_results: List[AgentResult] = []
        self.failed_agents: List[str] = []
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self._total_agents = len(AGENTS)

    def _notify(self, agent_name: str, completed: int, total: int, status: str) -> None:
        if self._progress_cb:
            try:
                self._progress_cb(agent_name, completed, total, status)
            except Exception:
                pass

    def run(self) -> ReviewReport:
        self.state = PipelineState.RUNNING
        self.started_at = utc_now()
        completed_count = 0

        def _run_agent(agent: Any) -> AgentResult:
            nonlocal completed_count
            try:
                result = agent.analyze(self.document)
                completed_count += 1
                self._notify(agent.AGENT_NAME if hasattr(agent, "AGENT_NAME") else str(agent),
                             completed_count, self._total_agents, "complete")
                return result
            except Exception as exc:
                completed_count += 1
                self._notify(agent.AGENT_NAME if hasattr(agent, "AGENT_NAME") else str(agent),
                             completed_count, self._total_agents, "failed")
                return AgentResult(
                    agent=agent.AGENT_NAME if hasattr(agent, "AGENT_NAME") else "unknown",
                    summary=f"Agent failed: {exc}",
                    findings=[],
                    limitations=[f"Agent error: {exc}"],
                )

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(_run_agent, agent): agent for agent in AGENTS}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    self.agent_results.append(result)
                except Exception as exc:
                    agent = futures[future]
                    name = agent.AGENT_NAME if hasattr(agent, "AGENT_NAME") else "unknown"
                    self.failed_agents.append(name)

        if self.failed_agents and not self.agent_results:
            self.state = PipelineState.FAILED
        elif self.failed_agents:
            self.state = PipelineState.PARTIAL
        else:
            self.state = PipelineState.COMPLETE

        self.completed_at = utc_now()
        return self._build_report()

    def _build_report(self) -> ReviewReport:
        findings = sorted(
            [f for r in self.agent_results for f in r.findings],
            key=lambda item: severity_weight(item.severity),
            reverse=True,
        )
        scores = _build_scores(self.agent_results, findings, self.document)
        score_explanations = _build_score_explanations(scores, self.agent_results, findings, self.document)
        doc_limitations = list(self.document.limitations)
        if self.failed_agents:
            doc_limitations.append(f"Failed agents: {', '.join(self.failed_agents)}")
        limitations = _merge_limitations(doc_limitations, self.agent_results)
        summary = _summary(scores, findings, self.document)
        action_plan = _action_plan(findings)
        review_id = str(uuid.uuid4())
        report = ReviewReport(
            review_id=review_id,
            created_at=self.completed_at or utc_now(),
            document=self.document.metadata,
            summary=summary,
            scores=scores,
            findings=findings,
            agents=self.agent_results,
            limitations=limitations,
            action_plan=action_plan,
            revision_history=[
                {
                    "timestamp": self.started_at or utc_now(),
                    "actor": "Mr Money AI",
                    "event": f"Review completed (state={self.state.value}, agents={len(self.agent_results)}/{self._total_agents})",
                }
            ],
        )
        report.score_explanations = score_explanations
        return report


def review_text(text: str, filename: str = "untitled.txt",
                parallel: bool = False, max_workers: int = 4,
                progress_callback: Optional[Callable[[str, int, int, str], None]] = None) -> ReviewReport:
    metadata = DocumentMetadata(filename=filename, file_format="txt",
                                content_type="text/plain",
                                size_bytes=len(text.encode("utf-8")))
    return review_document(Document(text=text, metadata=metadata),
                           parallel=parallel, max_workers=max_workers,
                           progress_callback=progress_callback)


def review_document(document: Document, parallel: bool = False,
                    max_workers: int = 4,
                    progress_callback: Optional[Callable[[str, int, int, str], None]] = None) -> ReviewReport:
    if parallel:
        pipeline = ReviewPipeline(document, max_workers=max_workers,
                                  progress_callback=progress_callback)
        return pipeline.run()

    agent_results: List[AgentResult] = []
    for i, agent in enumerate(AGENTS):
        name = agent.AGENT_NAME if hasattr(agent, "AGENT_NAME") else "unknown"
        try:
            result = agent.analyze(document)
            agent_results.append(result)
            if progress_callback:
                try:
                    progress_callback(name, i + 1, len(AGENTS), "complete")
                except Exception:
                    pass
        except Exception as exc:
            agent_results.append(AgentResult(
                agent=name, summary=f"Agent failed: {exc}",
                findings=[], limitations=[f"Agent error: {exc}"],
            ))
            if progress_callback:
                try:
                    progress_callback(name, i + 1, len(AGENTS), "failed")
                except Exception:
                    pass

    findings = sorted(
        [finding for result in agent_results for finding in result.findings],
        key=lambda item: severity_weight(item.severity),
        reverse=True,
    )
    scores = _build_scores(agent_results, findings, document)
    score_explanations = _build_score_explanations(scores, agent_results, findings, document)
    limitations = _merge_limitations(document.limitations, agent_results)
    summary = _summary(scores, findings, document)
    action_plan = _action_plan(findings)
    review_id = str(uuid.uuid4())
    created_at = utc_now()
    report = ReviewReport(
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
                "actor": "Mr Money AI",
                "event": "Initial automated review completed",
            }
        ],
    )
    report.score_explanations = score_explanations
    return report


def _merge_limitations(document_limitations: Iterable[str], agent_results: Iterable[AgentResult]) -> List[str]:
    seen: set[str] = set()
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


def _build_score_explanations(
    scores: Dict[str, float],
    agent_results: List[AgentResult],
    findings: List[Finding],
    document: Document,
) -> Dict[str, Dict[str, object]]:
    explanations: Dict[str, Dict[str, object]] = {}

    score_configs = {
        "publication_readiness": {
            "label": "Publication Readiness",
            "factors": ["writing_quality", "citation", "accessibility", "compliance", "security", "fact_checking"],
        },
        "writing_quality": {
            "label": "Writing Quality",
            "factors": ["grammar", "readability", "sentence_variety", "vocabulary_richness"],
        },
        "grammar": {"label": "Grammar", "factors": []},
        "readability": {"label": "Readability", "factors": []},
        "originality": {"label": "Originality", "factors": []},
        "citation": {"label": "Citation Quality", "factors": []},
        "accessibility": {"label": "Accessibility", "factors": []},
        "compliance": {"label": "Compliance", "factors": []},
        "security": {"label": "Security", "factors": []},
        "fact_checking": {"label": "Fact Verification", "factors": []},
        "ai_writing_indicator": {"label": "AI Writing Probability", "factors": []},
        "argument_strength_score": {"label": "Argument Strength", "factors": []},
        "sentence_variety_score": {"label": "Sentence Variety", "factors": []},
        "vocabulary_richness_score": {"label": "Vocabulary Richness", "factors": []},
        "paragraph_balance_score": {"label": "Paragraph Balance", "factors": []},
    }

    for key, value in scores.items():
        config = score_configs.get(key, {"label": key.replace("_", " ").title(), "factors": []})
        score_findings = [f for f in findings if f.category in key or key in f.category]

        if value >= 85:
            assessment = "Excellent"
            explanation = "This score indicates strong performance. "
        elif value >= 70:
            assessment = "Good"
            explanation = "Acceptable quality with room for improvement. "
        elif value >= 50:
            assessment = "Needs Work"
            explanation = "Significant improvements recommended before publication. "
        else:
            assessment = "Poor"
            explanation = "Critical issues found that require immediate attention. "

        if score_findings:
            top_finding = score_findings[0]
            explanation += f"Top issue: {top_finding.title}. {top_finding.recommendation}"

        evidence_agents = [r for r in agent_results if any(
            k in r.metrics for k in [key, key.replace("_score", "")]
        )]
        agent_evidence = [f"{r.agent}: {r.summary}" for r in evidence_agents[:2]]

        explanations[key] = {
            "score": value,
            "assessment": assessment,
            "explanation": explanation.strip(),
            "evidence": agent_evidence,
            "findingCount": len(score_findings),
            "confidence": 0.80 if len(findings) > 3 else 0.70,
        }

    return explanations
