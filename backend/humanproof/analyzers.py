"""Specialized local analysis agents for HumanProof AI."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import AgentResult, Document, Finding, TextSpan


WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'_-]*")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?", re.M)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
URL_RE = re.compile(r"https?://[^\s)>\]]+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
CITATION_RE = re.compile(r"\(([A-Z][A-Za-z'`-]+(?:\s+et al\.)?,?\s+\d{4}[a-z]?)\)|\[(\d+(?:,\s*\d+)*)\]")


def words(text: str) -> List[str]:
    return WORD_RE.findall(text)


def lower_words(text: str) -> List[str]:
    return [word.lower() for word in words(text)]


def sentences(text: str) -> List[str]:
    return [part.strip() for part in SENTENCE_RE.findall(text) if part.strip()]


def paragraphs(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 1)


def span_for(text: str, excerpt: str) -> TextSpan:
    start = text.find(excerpt)
    if start < 0:
        return TextSpan(excerpt=excerpt[:240])
    return TextSpan(start=start, end=start + len(excerpt), excerpt=excerpt[:240])


def syllable_count(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def severity_weight(severity: str) -> int:
    return {"info": 1, "low": 2, "medium": 4, "high": 7, "critical": 10}.get(severity, 1)


class GrammarAgent:
    name = "Grammar Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        sentence_list = sentences(text)

        repeated = re.finditer(r"\b([A-Za-z]+)\s+\1\b", text, flags=re.I)
        for match in list(repeated)[:10]:
            findings.append(
                Finding(
                    category="grammar",
                    severity="medium",
                    title="Repeated word",
                    message=f"The word '{match.group(1)}' appears twice in a row.",
                    recommendation="Remove the duplicate word unless the repetition is intentional.",
                    confidence=0.96,
                    agent=self.name,
                    span=TextSpan(match.start(), match.end(), match.group(0)),
                )
            )

        passive_matches = [
            sentence
            for sentence in sentence_list
            if re.search(r"\b(is|are|was|were|be|been|being)\s+\w+ed\b", sentence, flags=re.I)
        ]
        if passive_matches:
            findings.append(
                Finding(
                    category="style",
                    severity="low",
                    title="Passive voice concentration",
                    message=f"{len(passive_matches)} sentence(s) appear to use passive construction.",
                    recommendation="Prefer active voice where it improves accountability and clarity.",
                    confidence=0.72,
                    agent=self.name,
                    span=span_for(text, passive_matches[0]),
                    evidence={"examples": passive_matches[:3]},
                )
            )

        long_sentences = [sentence for sentence in sentence_list if len(words(sentence)) > 34]
        for sentence in long_sentences[:5]:
            findings.append(
                Finding(
                    category="clarity",
                    severity="medium",
                    title="Very long sentence",
                    message="A sentence is long enough to reduce readability.",
                    recommendation="Split the sentence or move secondary detail into a separate sentence.",
                    confidence=0.9,
                    agent=self.name,
                    span=span_for(text, sentence),
                    evidence={"wordCount": len(words(sentence))},
                )
            )

        punctuation_spacing = list(re.finditer(r"\s+[,.;:!?]", text))
        if punctuation_spacing:
            first = punctuation_spacing[0]
            findings.append(
                Finding(
                    category="grammar",
                    severity="low",
                    title="Spacing before punctuation",
                    message="One or more punctuation marks have a leading space.",
                    recommendation="Remove the space before punctuation marks.",
                    confidence=0.94,
                    agent=self.name,
                    span=TextSpan(first.start(), first.end(), first.group(0)),
                    evidence={"occurrences": len(punctuation_spacing)},
                )
            )

        penalty = sum(severity_weight(finding.severity) for finding in findings)
        score = clamp(100 - penalty)
        return AgentResult(
            agent=self.name,
            summary="Checked grammar, punctuation, sentence length, and common style issues.",
            metrics={"grammar_score": score, "style_score": clamp(score + 2)},
            findings=findings,
        )


class ReadabilityAgent:
    name = "Writing Agent"

    def analyze(self, document: Document) -> AgentResult:
        word_list = words(document.text)
        sentence_list = sentences(document.text)
        syllables = sum(syllable_count(word) for word in word_list)
        word_count = max(1, len(word_list))
        sentence_count = max(1, len(sentence_list))
        words_per_sentence = word_count / sentence_count
        syllables_per_word = syllables / word_count
        reading_ease = 206.835 - (1.015 * words_per_sentence) - (84.6 * syllables_per_word)
        grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
        score = clamp(reading_ease)

        findings: List[Finding] = []
        if reading_ease < 45:
            findings.append(
                Finding(
                    category="readability",
                    severity="medium",
                    title="Dense readability level",
                    message=f"Estimated reading ease is {reading_ease:.1f}, with grade level {grade:.1f}.",
                    recommendation="Shorten sentences, reduce stacked clauses, and define specialized terms.",
                    confidence=0.88,
                    agent=self.name,
                    evidence={"readingEase": round(reading_ease, 1), "gradeLevel": round(grade, 1)},
                )
            )
        if words_per_sentence > 24:
            findings.append(
                Finding(
                    category="flow",
                    severity="low",
                    title="High average sentence length",
                    message=f"Average sentence length is {words_per_sentence:.1f} words.",
                    recommendation="Vary sentence length to improve rhythm and scanning.",
                    confidence=0.87,
                    agent=self.name,
                )
            )

        vocabulary_diversity = len(set(word.lower() for word in word_list)) / word_count if word_list else 0
        return AgentResult(
            agent=self.name,
            summary="Estimated readability, grade level, vocabulary diversity, and sentence rhythm.",
            metrics={
                "readability_score": score,
                "estimated_grade_level": round(max(0.0, grade), 1),
                "vocabulary_diversity": round(vocabulary_diversity * 100, 1),
                "average_sentence_words": round(words_per_sentence, 1),
            },
            findings=findings,
        )


class StructureAgent:
    name = "Editing Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        paragraph_list = paragraphs(text)
        heading_matches = list(HEADING_RE.finditer(text))
        findings: List[Finding] = []

        if len(paragraph_list) > 5 and not heading_matches:
            findings.append(
                Finding(
                    category="structure",
                    severity="medium",
                    title="Long document without headings",
                    message="The document has multiple paragraphs but no detected headings.",
                    recommendation="Add descriptive headings to improve navigation and review workflows.",
                    confidence=0.86,
                    agent=self.name,
                )
            )

        weak_intro = paragraph_list and len(words(paragraph_list[0])) < 35 and len(paragraph_list) > 3
        if weak_intro:
            findings.append(
                Finding(
                    category="structure",
                    severity="low",
                    title="Thin opening section",
                    message="The first paragraph may be too short to establish context for the document.",
                    recommendation="Use the opening section to state purpose, scope, and intended outcome.",
                    confidence=0.68,
                    agent=self.name,
                    span=span_for(text, paragraph_list[0]),
                )
            )

        conclusion_terms = re.search(r"\b(conclusion|therefore|in summary|recommendation|next steps)\b", text[-1200:], re.I)
        if len(paragraph_list) > 6 and not conclusion_terms:
            findings.append(
                Finding(
                    category="structure",
                    severity="low",
                    title="No clear closing signal",
                    message="The ending does not clearly mark conclusion, recommendations, or next steps.",
                    recommendation="Add a closing section that summarizes decisions and required actions.",
                    confidence=0.64,
                    agent=self.name,
                )
            )

        paragraph_lengths = [len(words(paragraph)) for paragraph in paragraph_list]
        oversized = [length for length in paragraph_lengths if length > 180]
        if oversized:
            findings.append(
                Finding(
                    category="flow",
                    severity="medium",
                    title="Oversized paragraph",
                    message="At least one paragraph is long enough to slow scanning.",
                    recommendation="Break oversized paragraphs around one idea per paragraph.",
                    confidence=0.84,
                    agent=self.name,
                    evidence={"longParagraphWords": oversized[:5]},
                )
            )

        score = clamp(100 - sum(severity_weight(item.severity) for item in findings))
        return AgentResult(
            agent=self.name,
            summary="Reviewed document structure, headings, paragraph balance, and closing flow.",
            metrics={"structure_score": score, "heading_count": float(len(heading_matches)), "paragraph_count": float(len(paragraph_list))},
            findings=findings,
        )


class SimilarityAgent:
    name = "Similarity Agent"

    def analyze(self, document: Document) -> AgentResult:
        sentence_list = [sentence for sentence in sentences(document.text) if len(words(sentence)) >= 6]
        normalized = [re.sub(r"\W+", " ", sentence.lower()).strip() for sentence in sentence_list]
        counts = Counter(normalized)
        duplicate_sentences = [sentence_list[index] for index, item in enumerate(normalized) if counts[item] > 1]

        word_list = lower_words(document.text)
        shingles = [" ".join(word_list[index : index + 8]) for index in range(max(0, len(word_list) - 7))]
        shingle_counts = Counter(shingles)
        repeated_shingles = [item for item, count in shingle_counts.items() if count > 1 and len(item.split()) == 8]

        findings: List[Finding] = []
        if duplicate_sentences:
            findings.append(
                Finding(
                    category="similarity",
                    severity="medium",
                    title="Repeated sentence",
                    message=f"{len(duplicate_sentences)} repeated sentence occurrence(s) were found internally.",
                    recommendation="Remove accidental duplication or make repeated statements more purposeful.",
                    confidence=0.92,
                    agent=self.name,
                    span=span_for(document.text, duplicate_sentences[0]),
                    evidence={"examples": duplicate_sentences[:3]},
                )
            )
        if repeated_shingles:
            findings.append(
                Finding(
                    category="similarity",
                    severity="low",
                    title="Repeated phrase pattern",
                    message=f"{len(repeated_shingles)} repeated eight-word phrase pattern(s) were found.",
                    recommendation="Vary repeated phrasing unless it is required terminology.",
                    confidence=0.78,
                    agent=self.name,
                    evidence={"examples": repeated_shingles[:5]},
                )
            )

        total_units = max(1, len(sentence_list) + len(shingles))
        similarity_score = clamp(((len(duplicate_sentences) + len(repeated_shingles)) / total_units) * 100)
        originality_score = clamp(100 - similarity_score)
        return AgentResult(
            agent=self.name,
            summary="Checked exact and near internal repetition. Internet and cross-language matching require a source index.",
            metrics={"similarity_score": similarity_score, "originality_score": originality_score},
            findings=findings,
            limitations=["External plagiarism matching is not performed in local-only mode."],
        )


class CitationAgent:
    name = "Citation Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        dois = DOI_RE.findall(text)
        urls = URL_RE.findall(text)
        citations = [match.group(0) for match in CITATION_RE.finditer(text)]
        references_section = bool(re.search(r"(?im)^(references|bibliography|works cited)\s*$", text))
        findings: List[Finding] = []

        for url in urls[:20]:
            if not re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s]*)?$", url.rstrip(".,;")):
                findings.append(
                    Finding(
                        category="citation",
                        severity="medium",
                        title="Malformed URL",
                        message=f"The URL '{url[:80]}' may not be valid.",
                        recommendation="Repair the URL and verify that it resolves before publication.",
                        confidence=0.82,
                        agent=self.name,
                        span=span_for(text, url),
                    )
                )

        for doi in dois:
            if not re.match(r"^10\.\d{4,9}/\S+$", doi, flags=re.I):
                findings.append(
                    Finding(
                        category="citation",
                        severity="medium",
                        title="Malformed DOI",
                        message=f"The DOI '{doi}' does not match the expected DOI pattern.",
                        recommendation="Check the DOI against the publisher record or Crossref.",
                        confidence=0.83,
                        agent=self.name,
                        span=span_for(text, doi),
                    )
                )

        claim_sentences = [
            sentence
            for sentence in sentences(text)
            if re.search(r"\b(study|research|survey|report|data|evidence|statistics|percent|%)\b", sentence, re.I)
            and not DOI_RE.search(sentence)
            and not CITATION_RE.search(sentence)
        ]
        if claim_sentences:
            findings.append(
                Finding(
                    category="citation",
                    severity="medium",
                    title="Evidence claim without nearby citation",
                    message=f"{len(claim_sentences)} evidence-oriented sentence(s) do not include a nearby citation marker.",
                    recommendation="Add a citation or clarify that the sentence is original analysis.",
                    confidence=0.74,
                    agent=self.name,
                    span=span_for(text, claim_sentences[0]),
                    evidence={"examples": claim_sentences[:3]},
                )
            )

        if (citations or dois or urls) and not references_section:
            findings.append(
                Finding(
                    category="citation",
                    severity="low",
                    title="References section not detected",
                    message="Citation markers or source identifiers exist, but no references section was detected.",
                    recommendation="Add a references, bibliography, or works cited section in the required style.",
                    confidence=0.75,
                    agent=self.name,
                )
            )

        base = 100
        if not citations and not dois and not urls and len(words(text)) > 500:
            base -= 15
        base -= sum(severity_weight(item.severity) for item in findings)
        return AgentResult(
            agent=self.name,
            summary="Reviewed citation markers, DOI patterns, URL shape, and references-section presence.",
            metrics={
                "citation_score": clamp(base),
                "citation_count": float(len(citations)),
                "doi_count": float(len(dois)),
                "url_count": float(len(urls)),
            },
            findings=findings,
            limitations=["DOI and URL resolution require a network-enabled verification adapter."],
        )


class FactCheckingAgent:
    name = "Fact-Checking Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        year_now = 2026
        stat_sentences = [
            sentence
            for sentence in sentences(text)
            if re.search(r"\b\d+(?:\.\d+)?\s*(%|percent|million|billion|trillion|users|people|respondents)\b", sentence, re.I)
        ]
        unsupported_stats = [sentence for sentence in stat_sentences if not (CITATION_RE.search(sentence) or DOI_RE.search(sentence) or URL_RE.search(sentence))]
        if unsupported_stats:
            findings.append(
                Finding(
                    category="fact_checking",
                    severity="high",
                    title="Statistic without source",
                    message=f"{len(unsupported_stats)} statistic-bearing sentence(s) lack a visible source marker.",
                    recommendation="Attach a current source, DOI, URL, or reference entry to each statistic.",
                    confidence=0.82,
                    agent=self.name,
                    span=span_for(text, unsupported_stats[0]),
                    evidence={"examples": unsupported_stats[:3]},
                )
            )

        quoted = re.findall(r'"([^"\n]{12,240})"', text)
        if quoted and not (CITATION_RE.search(text) or DOI_RE.search(text) or URL_RE.search(text)):
            findings.append(
                Finding(
                    category="fact_checking",
                    severity="medium",
                    title="Quotation without verifiable source",
                    message="Quoted material appears without a visible source marker.",
                    recommendation="Provide the source, page number, URL, or citation for every quotation.",
                    confidence=0.76,
                    agent=self.name,
                    evidence={"quoteCount": len(quoted)},
                )
            )

        outdated_years = sorted({int(year) for year in re.findall(r"\b(20[0-1]\d|2020)\b", text)})
        if outdated_years and re.search(r"\b(current|recent|latest|today|now)\b", text, re.I):
            findings.append(
                Finding(
                    category="fact_checking",
                    severity="medium",
                    title="Potentially outdated source date",
                    message=f"The document uses current-language framing near older year(s): {outdated_years[:5]}.",
                    recommendation=f"Verify whether the data is still current as of {year_now}.",
                    confidence=0.67,
                    agent=self.name,
                    evidence={"years": outdated_years[:10]},
                )
            )

        score = clamp(100 - sum(severity_weight(item.severity) for item in findings))
        return AgentResult(
            agent=self.name,
            summary="Flagged statistics, quotations, and time-sensitive claims that need source verification.",
            metrics={"fact_check_score": score, "unsupported_statements": float(len(unsupported_stats))},
            findings=findings,
            limitations=["This local agent flags verification needs; it does not independently prove claims true or false."],
        )


class AIWritingAnalysisAgent:
    name = "Transparent AI-Writing Analysis Agent"

    def analyze(self, document: Document) -> AgentResult:
        sentence_list = sentences(document.text)
        word_list = lower_words(document.text)
        findings: List[Finding] = []

        if not sentence_list or not word_list:
            return AgentResult(
                agent=self.name,
                summary="Not enough text for probabilistic writing-pattern analysis.",
                metrics={"ai_writing_indicator": 0.0, "ai_analysis_confidence": 0.0},
                findings=[],
                limitations=["Short or empty text cannot be meaningfully analyzed."],
            )

        lengths = [len(words(sentence)) for sentence in sentence_list]
        diversity = len(set(word_list)) / max(1, len(word_list))
        starts = [words(sentence)[0].lower() for sentence in sentence_list if words(sentence)]
        repeated_start_rate = 1 - (len(set(starts)) / max(1, len(starts)))
        length_std = pstdev(lengths) if len(lengths) > 1 else 0.0
        rhythm_uniformity = 1 - min(1.0, length_std / 18.0)
        top_word_share = sum(count for _, count in Counter(word_list).most_common(12)) / max(1, len(word_list))

        indicator = clamp(
            (rhythm_uniformity * 32)
            + (max(0.0, 0.52 - diversity) * 55)
            + (repeated_start_rate * 24)
            + (max(0.0, top_word_share - 0.24) * 70)
        )
        confidence = clamp(min(1.0, len(word_list) / 900) * 100)

        if indicator >= 55:
            findings.append(
                Finding(
                    category="ai_analysis",
                    severity="info",
                    title="Structured-writing indicators detected",
                    message="The text has a comparatively uniform rhythm, repeated sentence starts, or low lexical variety.",
                    recommendation="Use this as a revision signal only. Review the highlighted patterns and preserve author intent.",
                    confidence=round(confidence / 100, 2),
                    agent=self.name,
                    evidence={
                        "vocabularyDiversity": round(diversity, 3),
                        "rhythmUniformity": round(rhythm_uniformity, 3),
                        "repeatedStartRate": round(repeated_start_rate, 3),
                    },
                )
            )

        return AgentResult(
            agent=self.name,
            summary="Estimated probabilistic writing-pattern indicators without making a definitive authorship claim.",
            metrics={"ai_writing_indicator": indicator, "ai_analysis_confidence": confidence},
            findings=findings,
            limitations=[
                "AI-writing indicators are probabilistic and can be wrong.",
                "The result must not be used as sole evidence of misconduct or authorship.",
            ],
        )


class ToneSentimentAgent:
    name = "Tone Analysis Agent"
    positive = {"clear", "effective", "improve", "benefit", "strong", "accurate", "trusted", "secure", "successful"}
    negative = {"risk", "weak", "unclear", "fail", "failed", "problem", "harm", "inaccurate", "unsafe", "delay"}

    def analyze(self, document: Document) -> AgentResult:
        word_list = lower_words(document.text)
        positive_count = sum(1 for word in word_list if word in self.positive)
        negative_count = sum(1 for word in word_list if word in self.negative)
        total = max(1, positive_count + negative_count)
        sentiment = ((positive_count - negative_count) / total) if total else 0.0
        hedges = len(re.findall(r"\b(may|might|could|possibly|perhaps|generally|often)\b", document.text, re.I))
        absolutes = len(re.findall(r"\b(always|never|guaranteed|certainly|undeniably|proves)\b", document.text, re.I))
        findings: List[Finding] = []

        if absolutes > hedges + 3:
            findings.append(
                Finding(
                    category="tone",
                    severity="low",
                    title="High certainty language",
                    message="The document uses several absolute terms.",
                    recommendation="Use precise qualifiers where claims depend on context or evidence.",
                    confidence=0.7,
                    agent=self.name,
                    evidence={"absoluteTerms": absolutes, "qualifiers": hedges},
                )
            )

        return AgentResult(
            agent=self.name,
            summary="Measured sentiment balance, certainty language, and tone risk signals.",
            metrics={"tone_score": clamp(100 - sum(severity_weight(item.severity) for item in findings)), "sentiment_balance": round(sentiment * 100, 1)},
            findings=findings,
        )


class AuthorshipConsistencyAgent:
    name = "Authorship Consistency Agent"

    def analyze(self, document: Document) -> AgentResult:
        paragraph_list = [paragraph for paragraph in paragraphs(document.text) if len(words(paragraph)) >= 20]
        findings: List[Finding] = []
        if len(paragraph_list) < 4:
            return AgentResult(
                agent=self.name,
                summary="Document is too short for useful cross-section authorship consistency analysis.",
                metrics={"authorship_consistency_score": 100.0},
                limitations=["At least four substantial paragraphs are recommended for this analysis."],
            )

        lengths = [mean([len(word) for word in words(paragraph)]) for paragraph in paragraph_list]
        sentence_lengths = [mean([len(words(sentence)) for sentence in sentences(paragraph)] or [0]) for paragraph in paragraph_list]
        combined_variance = (pstdev(lengths) * 18) + (pstdev(sentence_lengths) * 3)
        score = clamp(100 - combined_variance)
        if score < 72:
            findings.append(
                Finding(
                    category="authorship",
                    severity="info",
                    title="Style variation across sections",
                    message="Some sections differ noticeably in word length or sentence rhythm.",
                    recommendation="Review section transitions and terminology to ensure a consistent authorial voice.",
                    confidence=0.62,
                    agent=self.name,
                    evidence={"styleVariance": round(combined_variance, 2)},
                )
            )
        return AgentResult(
            agent=self.name,
            summary="Compared style features across document sections for consistency signals.",
            metrics={"authorship_consistency_score": score},
            findings=findings,
            limitations=["Style variation can be caused by normal editing, quotations, templates, or multiple contributors."],
        )


class AccessibilityAgent:
    name = "Accessibility Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        image_refs = re.findall(r"!\[([^\]]*)\]\([^)]+\)|<img\b[^>]*>", text, flags=re.I)
        missing_alt = 0
        for match in image_refs:
            if isinstance(match, tuple):
                alt = match[0]
                if not alt.strip():
                    missing_alt += 1
            elif "alt=" not in match.lower():
                missing_alt += 1
        if missing_alt:
            findings.append(
                Finding(
                    category="accessibility",
                    severity="medium",
                    title="Image alt text missing",
                    message=f"{missing_alt} image reference(s) appear to lack alt text.",
                    recommendation="Add concise alt text that communicates the purpose of each meaningful image.",
                    confidence=0.9,
                    agent=self.name,
                    evidence={"missingAltText": missing_alt},
                )
            )

        heading_levels = [len(match.group(1)) for match in HEADING_RE.finditer(text)]
        jumps = [(heading_levels[index - 1], level) for index, level in enumerate(heading_levels[1:], start=1) if level - heading_levels[index - 1] > 1]
        if jumps:
            findings.append(
                Finding(
                    category="accessibility",
                    severity="low",
                    title="Heading level jump",
                    message="Heading hierarchy skips one or more levels.",
                    recommendation="Keep headings sequential so assistive technologies can navigate the document.",
                    confidence=0.86,
                    agent=self.name,
                    evidence={"jumps": jumps[:5]},
                )
            )

        link_texts = re.findall(r"\[([^\]]+)\]\(https?://[^)]+\)", text)
        vague_links = [label for label in link_texts if label.lower().strip() in {"click here", "here", "link", "read more"}]
        if vague_links:
            findings.append(
                Finding(
                    category="accessibility",
                    severity="low",
                    title="Vague link text",
                    message="Some links use non-descriptive labels.",
                    recommendation="Use link text that describes the destination or action.",
                    confidence=0.82,
                    agent=self.name,
                    evidence={"examples": vague_links[:5]},
                )
            )

        score = clamp(100 - sum(severity_weight(item.severity) for item in findings))
        return AgentResult(
            agent=self.name,
            summary="Checked alt text, heading hierarchy, and descriptive links where text markup is available.",
            metrics={"accessibility_score": score},
            findings=findings,
            limitations=["Color contrast and reading order require rendered document inspection."],
        )


class ComplianceSecurityAgent:
    name = "Compliance and Security Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        email_matches = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
        secret_matches = re.findall(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{12,})", text, flags=re.I)
        card_like = re.findall(r"\b(?:\d[ -]*?){13,16}\b", text)

        if email_matches:
            findings.append(
                Finding(
                    category="privacy",
                    severity="low",
                    title="Personal data present",
                    message=f"{len(email_matches)} email address(es) were detected.",
                    recommendation="Confirm the document has a lawful basis, retention rule, and intended audience for personal data.",
                    confidence=0.93,
                    agent=self.name,
                    evidence={"sample": email_matches[:3]},
                )
            )
        if secret_matches:
            findings.append(
                Finding(
                    category="security",
                    severity="critical",
                    title="Possible credential exposed",
                    message="The document appears to contain a token, secret, password, or API key.",
                    recommendation="Remove the credential, rotate it, and review access logs.",
                    confidence=0.85,
                    agent=self.name,
                )
            )
        if card_like:
            findings.append(
                Finding(
                    category="security",
                    severity="high",
                    title="Payment-card-like number detected",
                    message="A 13-16 digit number pattern appears in the document.",
                    recommendation="Redact payment information unless storage is explicitly approved and compliant.",
                    confidence=0.68,
                    agent=self.name,
                    evidence={"occurrences": len(card_like)},
                )
            )

        compliance_score = clamp(100 - sum(severity_weight(item.severity) for item in findings if item.category in {"privacy", "compliance"}))
        security_score = clamp(100 - sum(severity_weight(item.severity) for item in findings if item.category == "security"))
        return AgentResult(
            agent=self.name,
            summary="Checked privacy, credential, and sensitive-data risk patterns.",
            metrics={"compliance_score": compliance_score, "security_score": security_score},
            findings=findings,
            limitations=["Regulatory conclusions require organization policy configuration and legal review."],
        )


class ArgumentStrengthAgent:
    name = "Argument Strength Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        paras = paragraphs(text)

        vague_words = ["things", "stuff", "a lot", "very", "really", "quite", "somewhat", "maybe", "perhaps", "might"]
        for para in paras:
            for vw in vague_words:
                count = len(re.findall(r"\b" + vw + r"\b", para, re.I))
                if count > 1:
                    span = span_for(text, para[:120])
                    findings.append(Finding(
                        category="argument_strength",
                        severity="medium",
                        title=f"Vague language: '{vw}' repeated {count} times",
                        message=f"This paragraph uses the vague term '{vw}' multiple times, weakening the argument.",
                        recommendation=f"Replace '{vw}' with specific data, numbers, or concrete examples.",
                        confidence=0.80,
                        agent=self.name,
                        span=span,
                    ))

        claim_words = ["demonstrates", "proves", "shows", "confirms", "establishes", "verifies"]
        evidence_words = ["study", "research", "data", "evidence", "finding", "result", "survey", "trial"]
        for para in paras:
            has_claim = any(w in para.lower() for w in claim_words)
            has_evidence = any(w in para.lower() for w in evidence_words)
            if has_claim and not has_evidence and len(words(para)) > 30:
                span = span_for(text, para[:120])
                findings.append(Finding(
                    category="argument_strength",
                    severity="medium",
                    title="Claim without supporting evidence",
                    message="A paragraph makes a strong claim but does not reference supporting evidence.",
                    recommendation="Add citations, data, or references to substantiate the claim.",
                    confidence=0.72,
                    agent=self.name,
                    span=span,
                ))

        strength_score = clamp(100 - sum(severity_weight(f.severity) * 5 for f in findings))
        return AgentResult(
            agent=self.name,
            summary="Assessed argument strength, vague language, and evidence backing.",
            metrics={"argument_strength_score": strength_score},
            findings=findings,
            limitations=["Argument quality assessment is heuristic-based and may miss domain-specific nuances."],
        )


class SentenceVarietyAgent:
    name = "Sentence Variety Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        sents = sentences(text)
        if len(sents) < 5:
            return AgentResult(agent=self.name, summary="Not enough sentences for variety analysis.", metrics={}, findings=[])

        lengths = [len(words(s)) for s in sents]
        avg_len = mean(lengths)
        std = pstdev(lengths) if len(lengths) > 1 else 0

        if std < 3:
            findings.append(Finding(
                category="sentence_variety",
                severity="low",
                title="Low sentence length variation",
                message=f"Standard deviation of sentence length is {std:.1f} words, suggesting monotonous rhythm.",
                recommendation="Mix short punchy sentences with longer complex ones for better readability.",
                confidence=0.85,
                agent=self.name,
            ))

        start_words = [s.strip().split()[0].lower() if s.strip().split() else "" for s in sents]
        start_counts = Counter(start_words)
        for word, count in start_counts.most_common(5):
            if count >= 4 and count / len(sents) > 0.25:
                findings.append(Finding(
                    category="sentence_variety",
                    severity="low",
                    title=f"Repetitive sentence starts: '{word}'",
                    message=f"{count} sentences start with '{word}', reducing readability.",
                    recommendation="Vary sentence openings using different parts of speech or transitional phrases.",
                    confidence=0.88,
                    agent=self.name,
                ))

        variety_score = clamp(100 - sum(severity_weight(f.severity) * 4 for f in findings))
        return AgentResult(
            agent=self.name,
            summary="Analyzed sentence length variation and opening patterns.",
            metrics={"sentence_variety_score": variety_score, "avg_sentence_length": round(avg_len, 1)},
            findings=findings,
            limitations=[],
        )


class VocabularyRichnessAgent:
    name = "Vocabulary Richness Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        all_words = lower_words(text)
        if len(all_words) < 50:
            return AgentResult(agent=self.name, summary="Not enough words for vocabulary analysis.", metrics={}, findings=[])

        unique = set(all_words)
        ttr = len(unique) / len(all_words)
        if ttr < 0.4:
            findings.append(Finding(
                category="vocabulary",
                severity="medium",
                title="Low vocabulary diversity",
                message=f"Type-token ratio is {ttr:.2f} (unique words / total words), indicating repetitive vocabulary.",
                recommendation="Use synonyms, varied phrasing, and domain-specific terminology to enrich the text.",
                confidence=0.82,
                agent=self.name,
            ))

        word_freq = Counter(all_words)
        top重复 = [(w, c) for w, c in word_freq.most_common(20) if len(w) > 3 and c > len(all_words) * 0.03]
        for word, count in top重复[:3]:
            findings.append(Finding(
                category="vocabulary",
                severity="info",
                title=f"High-frequency word: '{word}' ({count}x)",
                message=f"The word '{word}' appears {count} times ({count*100/len(all_words):.1f}% of text).",
                recommendation=f"Consider substituting '{word}' with synonyms in some instances.",
                confidence=0.90,
                agent=self.name,
            ))

        richness_score = clamp(ttr * 200)
        return AgentResult(
            agent=self.name,
            summary=f"Vocabulary diversity (TTR): {ttr:.2f}. {'Good variety.' if ttr > 0.55 else 'Consider enriching vocabulary.'}",
            metrics={"vocabulary_richness_score": richness_score, "type_token_ratio": round(ttr, 3)},
            findings=findings,
            limitations=["TTR is sensitive to document length; short texts naturally have lower diversity."],
        )


class ParagraphBalanceAgent:
    name = "Paragraph Balance Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        paras = paragraphs(text)
        if len(paras) < 2:
            return AgentResult(agent=self.name, summary="Not enough paragraphs for balance analysis.", metrics={}, findings=[])

        para_lengths = [len(words(p)) for p in paras]
        avg = mean(para_lengths)

        for i, (para, plen) in enumerate(zip(paras, para_lengths)):
            if plen > avg * 3 and plen > 100:
                span = span_for(text, para[:100])
                findings.append(Finding(
                    category="paragraph_balance",
                    severity="low",
                    title=f"Very long paragraph ({plen} words)",
                    message=f"Paragraph {i+1} is {plen} words, over 3x the average ({avg:.0f}).",
                    recommendation="Break into smaller paragraphs with clear topic sentences.",
                    confidence=0.90,
                    agent=self.name,
                    span=span,
                ))
            elif plen < 15 and i > 0 and i < len(paras) - 1:
                findings.append(Finding(
                    category="paragraph_balance",
                    severity="info",
                    title=f"Very short paragraph ({plen} words)",
                    message=f"Paragraph {i+1} has only {plen} words. Consider merging with adjacent paragraphs.",
                    recommendation="Combine short paragraphs or expand with supporting details.",
                    confidence=0.70,
                    agent=self.name,
                ))

        balance_score = clamp(100 - sum(severity_weight(f.severity) * 3 for f in findings))
        return AgentResult(
            agent=self.name,
            summary=f"Analyzed {len(paras)} paragraphs. Average length: {avg:.0f} words.",
            metrics={"paragraph_balance_score": balance_score, "avg_paragraph_length": round(avg, 1)},
            findings=findings,
            limitations=[],
        )


class PIIDetectionAgent:
    name = "PII Detection Agent"

    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
    SSN_RE = re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b")
    IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []

        for match in self.EMAIL_RE.finditer(text):
            email = match.group()
            if not email.endswith((".com", ".org", ".edu", ".gov", ".net", ".io")):
                span = span_for(text, email)
                findings.append(Finding(
                    category="pii",
                    severity="medium",
                    title="Email address detected",
                    message=f"Found email address: {email}",
                    recommendation="Verify this is intentional contact information and not personal data requiring protection.",
                    confidence=0.95,
                    agent=self.name,
                    span=span,
                ))

        for match in self.PHONE_RE.finditer(text):
            phone = match.group()
            span = span_for(text, phone)
            findings.append(Finding(
                category="pii",
                severity="medium",
                title="Phone number detected",
                message=f"Found phone number: {phone}",
                recommendation="Ensure this is necessary contact information and comply with privacy policies.",
                confidence=0.85,
                agent=self.name,
                span=span,
            ))

        for match in self.SSN_RE.finditer(text):
            ssn = match.group()
            span = span_for(text, ssn)
            findings.append(Finding(
                category="pii",
                severity="critical",
                title="Potential SSN detected",
                message="A 9-digit number pattern resembling a Social Security Number was found.",
                recommendation="IMMEDIATELY remove or redact this number. SSNs should never appear in shared documents.",
                confidence=0.60,
                agent=self.name,
                span=span,
            ))

        pii_score = clamp(100 - sum(severity_weight(f.severity) * 8 for f in findings))
        return AgentResult(
            agent=self.name,
            summary=f"Scanned for PII patterns. Found {len(findings)} potential exposure(s).",
            metrics={"pii_score": pii_score},
            findings=findings,
            limitations=["Pattern-based detection may produce false positives. Manual review recommended for high-severity findings."],
        )


class DocumentClassificationAgent:
    name = "Document Classification Agent"

    def analyze(self, document: Document) -> AgentResult:
        text = document.text
        findings: List[Finding] = []
        word_list = lower_words(text)
        word_count = len(word_list)

        academic_signals = ["abstract", "methodology", "hypothesis", "literature review", "references", "doi", "et al.", "journal"]
        business_signals = ["executive summary", "quarterly", "revenue", "stakeholder", "roi", "budget", "deliverable"]
        technical_signals = ["architecture", "api", "implementation", "deployment", "algorithm", "database", "endpoint"]
        legal_signals = ["hereby", "whereas", "pursuant to", "notwithstanding", "shall", "party", "agreement"]

        signals = {
            "academic": sum(1 for s in academic_signals if s in text.lower()),
            "business": sum(1 for s in business_signals if s in text.lower()),
            "technical": sum(1 for s in technical_signals if s in text.lower()),
            "legal": sum(1 for s in legal_signals if s in text.lower()),
        }
        doc_type = max(signals, key=signals.get) if max(signals.values()) > 0 else "general"

        findings.append(Finding(
            category="classification",
            severity="info",
            title=f"Document type: {doc_type.title()}",
            message=f"Detected {doc_type} writing style based on vocabulary and structure signals.",
            recommendation=f"Ensure the document follows {doc_type}-specific formatting and conventions.",
            confidence=0.75,
            agent=self.name,
            evidence={"signals": signals, "word_count": word_count},
        ))

        return AgentResult(
            agent=self.name,
            summary=f"Classified as {doc_type} document ({word_count} words).",
            metrics={"document_type_confidence": signals.get(doc_type, 0) * 25},
            findings=findings,
            limitations=["Classification is heuristic-based. Complex documents may blend multiple types."],
        )


AGENTS = [
    GrammarAgent(),
    ReadabilityAgent(),
    StructureAgent(),
    SimilarityAgent(),
    CitationAgent(),
    FactCheckingAgent(),
    AIWritingAnalysisAgent(),
    ToneSentimentAgent(),
    AuthorshipConsistencyAgent(),
    AccessibilityAgent(),
    ComplianceSecurityAgent(),
    ArgumentStrengthAgent(),
    SentenceVarietyAgent(),
    VocabularyRichnessAgent(),
    ParagraphBalanceAgent(),
    PIIDetectionAgent(),
    DocumentClassificationAgent(),
]

