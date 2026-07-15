"""Style guide enforcement for Mr Money AI.

Provides tone presets, term glossary, custom rule engine,
and document-style scoring against a configured guide.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class Tone(str, Enum):
    FORMAL = "formal"
    INFORMAL = "informal"
    TECHNICAL = "technical"
    ACADEMIC = "academic"
    CREATIVE = "creative"
    BUSINESS = "business"


@dataclass
class StyleTerm:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    term: str = ""
    preferred: str = ""
    category: str = "terminology"
    description: str = ""
    severity: str = "medium"
    org_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StyleRule:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    pattern: str = ""
    replacement: str = ""
    severity: str = "medium"
    enabled: bool = True
    org_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def matches(self, text: str) -> List[re.Match[str]]:
        try:
            return list(re.finditer(self.pattern, text, re.IGNORECASE))
        except re.error:
            return []


@dataclass
class StyleViolation:
    rule_id: str = ""
    rule_name: str = ""
    message: str = ""
    severity: str = "medium"
    position: int = 0
    excerpt: str = ""
    suggestion: str = ""


@dataclass
class StyleCheckResult:
    score: float = 100.0
    violations: List[StyleViolation] = field(default_factory=list)
    term_suggestions: List[Dict[str, str]] = field(default_factory=list)
    tone_detected: str = ""
    summary: str = ""
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


TONE_PRESETS: Dict[Tone, Dict[str, Any]] = {
    Tone.FORMAL: {
        "avoid_words": ["gonna", "wanna", "gotta", "kinda", "sorta", "dunno"],
        "avoid_contractions": True,
        "min_sentence_length": 10,
        "max_exclamation_marks": 0,
        "passive_voice_max_ratio": 0.3,
    },
    Tone.INFORMAL: {
        "avoid_words": [],
        "avoid_contractions": False,
        "min_sentence_length": 3,
        "max_exclamation_marks": 5,
        "passive_voice_max_ratio": 0.5,
    },
    Tone.TECHNICAL: {
        "avoid_words": ["thing", "stuff", "a lot", "very", "really"],
        "avoid_contractions": True,
        "min_sentence_length": 12,
        "max_exclamation_marks": 0,
        "passive_voice_max_ratio": 0.4,
    },
    Tone.ACADEMIC: {
        "avoid_words": ["gonna", "wanna", "gotta", "thing", "stuff"],
        "avoid_contractions": True,
        "min_sentence_length": 15,
        "max_exclamation_marks": 0,
        "passive_voice_max_ratio": 0.35,
    },
    Tone.CREATIVE: {
        "avoid_words": [],
        "avoid_contractions": False,
        "min_sentence_length": 3,
        "max_exclamation_marks": 10,
        "passive_voice_max_ratio": 0.6,
    },
    Tone.BUSINESS: {
        "avoid_words": ["gonna", "wanna", "gotta", "synergy", "leverage"],
        "avoid_contractions": True,
        "min_sentence_length": 10,
        "max_exclamation_marks": 1,
        "passive_voice_max_ratio": 0.25,
    },
}


def _count_contractions(text: str) -> int:
    return len(re.findall(r"\b\w+'\w+\b", text))


def _count_passive_voice(text: str) -> int:
    return len(re.findall(
        r"\b(is|are|was|were|be|been|being)\s+(being\s+)?\w+ed\b",
        text, re.IGNORECASE
    ))


def _detect_tone(text: str) -> str:
    text_lower = text.lower()
    words = text_lower.split()
    total = max(len(words), 1)
    formal_score = 0
    informal_score = 0
    technical_score = 0
    informal_markers = ["gonna", "wanna", "gotta", "kinda", "lol", "omg", "btw"]
    formal_markers = ["furthermore", "moreover", "consequently", "nevertheless",
                      "henceforth", "aforementioned", "wherein"]
    technical_markers = ["algorithm", "implementation", "architecture", "parameter",
                         "optimization", "infrastructure", "config"]
    for w in words:
        if w in informal_markers:
            informal_score += 1
        if w in formal_markers:
            formal_score += 1
        if w in technical_markers:
            technical_score += 1
    avg_len = sum(len(w) for w in words) / total
    if avg_len > 6:
        formal_score += 2
        technical_score += 1
    if avg_len < 4:
        informal_score += 2
    scores = {
        "formal": formal_score, "informal": informal_score,
        "technical": technical_score, "academic": formal_score + 1,
        "business": formal_score, "creative": informal_score + 1,
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "formal"


class StyleGuide:
    def __init__(self, org_id: str = "", default_tone: Tone = Tone.FORMAL) -> None:
        self.org_id = org_id
        self.default_tone = default_tone
        self._terms: Dict[str, StyleTerm] = {}
        self._rules: Dict[str, StyleRule] = {}

    def add_term(self, term: str, preferred: str = "",
                 category: str = "terminology",
                 description: str = "",
                 severity: str = "medium") -> StyleTerm:
        t = StyleTerm(
            term=term, preferred=preferred, category=category,
            description=description, severity=severity, org_id=self.org_id,
        )
        self._terms[t.id] = t
        return t

    def remove_term(self, term_id: str) -> bool:
        return self._terms.pop(term_id, None) is not None

    def list_terms(self) -> List[StyleTerm]:
        return list(self._terms.values())

    def add_rule(self, name: str, pattern: str, replacement: str = "",
                 description: str = "",
                 severity: str = "medium") -> StyleRule:
        rule = StyleRule(
            name=name, pattern=pattern, replacement=replacement,
            description=description, severity=severity, org_id=self.org_id,
        )
        self._rules[rule.id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> List[StyleRule]:
        return list(self._rules.values())

    def check_document(self, text: str,
                       tone: Optional[Tone] = None) -> StyleCheckResult:
        active_tone = tone or self.default_tone
        violations: List[StyleViolation] = []
        term_suggestions: List[Dict[str, str]] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue
            matches = rule.matches(text)
            for m in matches:
                excerpt_start = max(0, m.start() - 20)
                excerpt_end = min(len(text), m.end() + 20)
                violations.append(StyleViolation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    message=f"Rule '{rule.name}' matched: {m.group()}",
                    severity=rule.severity,
                    position=m.start(),
                    excerpt=text[excerpt_start:excerpt_end],
                    suggestion=rule.replacement,
                ))

        for term_rec in self._terms.values():
            pattern = re.compile(r"\b" + re.escape(term_rec.term) + r"\b",
                                 re.IGNORECASE)
            for m in pattern.finditer(text):
                if term_rec.preferred and m.group() != term_rec.preferred:
                    term_suggestions.append({
                        "term": term_rec.term,
                        "preferred": term_rec.preferred,
                        "position": m.start(),
                        "category": term_rec.category,
                    })

        preset = TONE_PRESETS.get(active_tone, TONE_PRESETS[Tone.FORMAL])
        if preset.get("avoid_contractions"):
            n_contractions = _count_contractions(text)
            if n_contractions > 0:
                violations.append(StyleViolation(
                    rule_id="tone_contraction",
                    rule_name="No Contractions",
                    message=f"Found {n_contractions} contraction(s) in {active_tone.value} tone",
                    severity="low",
                    suggestion="Expand contractions for formal tone",
                ))

        for bad_word in preset.get("avoid_words", []):
            pattern = re.compile(r"\b" + re.escape(bad_word) + r"\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                violations.append(StyleViolation(
                    rule_id="tone_avoid_word",
                    rule_name=f"Avoid '{bad_word}'",
                    message=f"Word '{bad_word}' should be avoided in {active_tone.value} tone",
                    severity="low",
                    position=m.start(),
                ))

        max_excl = preset.get("max_exclamation_marks", 0)
        excl_count = text.count("!")
        if excl_count > max_excl:
            violations.append(StyleViolation(
                rule_id="tone_exclamation",
                rule_name="Excessive Exclamation Marks",
                message=f"Found {excl_count} exclamation mark(s), max {max_excl} for {active_tone.value}",
                severity="low",
                suggestion="Reduce exclamation marks",
            ))

        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        min_len = preset.get("min_sentence_length", 5)
        short = [s for s in sentences if len(s.split()) < min_len]
        if short:
            violations.append(StyleViolation(
                rule_id="tone_short_sentences",
                rule_name="Short Sentences",
                message=f"{len(short)} sentence(s) shorter than {min_len} words",
                severity="info",
                suggestion=f"Expand sentences to at least {min_len} words",
            ))

        passive_count = _count_passive_voice(text)
        total_sentences = max(len(sentences), 1)
        passive_ratio = passive_count / total_sentences
        max_passive = preset.get("passive_voice_max_ratio", 0.3)
        if passive_ratio > max_passive:
            violations.append(StyleViolation(
                rule_id="tone_passive_voice",
                rule_name="Excessive Passive Voice",
                message=f"Passive voice ratio {passive_ratio:.0%} exceeds {max_passive:.0%}",
                severity="medium",
                suggestion="Convert passive constructions to active voice",
            ))

        penalty = sum(
            {"high": 15, "medium": 8, "low": 3, "info": 1}.get(v.severity, 1)
            for v in violations
        )
        score = max(0.0, 100.0 - penalty)
        detected_tone = _detect_tone(text)

        summary_parts = []
        if violations:
            summary_parts.append(f"{len(violations)} violation(s) found")
        if term_suggestions:
            summary_parts.append(f"{len(term_suggestions)} term suggestion(s)")
        summary = "; ".join(summary_parts) if summary_parts else "Document passes style guide"

        return StyleCheckResult(
            score=score,
            violations=violations,
            term_suggestions=term_suggestions,
            tone_detected=detected_tone,
            summary=summary,
        )
