"""Specialized AI agent implementations for Mr Money AI.

Each agent handles a specific domain and returns structured results
with response text, confidence score, and source references.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import search
except ImportError:
    search = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Base protocol and utilities
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = {
    "python": {"extensions": (".py",), "keywords": ["def", "import", "class", "self", "lambda", "yield"]},
    "javascript": {"extensions": (".js", ".jsx", ".mjs"), "keywords": ["function", "const", "let", "var", "async", "await", "require"]},
    "typescript": {"extensions": (".ts", ".tsx"), "keywords": ["interface", "type", "enum", "namespace", "declare", "readonly"]},
    "java": {"extensions": (".java",), "keywords": ["public", "private", "protected", "extends", "implements", "interface"]},
    "csharp": {"extensions": (".cs",), "keywords": ["using", "namespace", "var", "async", "await", "readonly"]},
    "go": {"extensions": (".go",), "keywords": ["func", "package", "import", "goroutine", "chan", "defer"]},
    "rust": {"extensions": (".rs",), "keywords": ["fn", "let", "mut", "impl", "trait", "struct", "enum", "match"]},
}

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "research": ["research", "study", "investigate", "explore", "find sources", "literature", "papers", "references", "discover"],
    "coding": ["code", "function", "debug", "error", "bug", "implement", "refactor", "compile", "syntax", "programming", "api", "algorithm"],
    "data": ["data", "csv", "json", "statistics", "analyze data", "dataset", "metrics", "trends", "visualization", "chart", "graph"],
    "writing": ["write", "rewrite", "edit", "grammar", "proofread", "tone", "clarity", "content", "outline", "draft", "improve text"],
    "business": ["business", "market", "swot", "competitor", "revenue", "strategy", "plan", "roi", "stakeholder", "growth"],
    "strategy": ["goal", "roadmap", "timeline", "action plan", "milestone", "risk", "decompose", "priority", "roadmap", "deadline"],
}


def _empty_result(response: str = "", confidence: float = 0.0) -> Dict[str, Any]:
    return {"response": response, "confidence": confidence, "sources": []}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return round(max(lo, min(hi, value)), 3)


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------

class ResearchAgent:
    """Researches topics using available search infrastructure."""

    name = "ResearchAgent"
    description = "Researches topics, finds sources, and synthesizes information."

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        sources: List[Dict[str, str]] = []
        response_parts: List[str] = []

        if search is not None and hasattr(search, "research_topic"):
            try:
                result = search.research_topic(query)
                if isinstance(result, dict):
                    sources = result.get("sources", [])
                    response_parts.append(result.get("summary", result.get("response", "")))
                elif isinstance(result, list):
                    sources = result
            except Exception as exc:
                response_parts.append(f"Search module error: {exc}")

        if not sources:
            sources = [{"title": "Local analysis", "snippet": f"Research query: {query}"}]
            response_parts.append(
                f"No external search available. Analyzing query locally.\n"
                f"Query: {query}\n"
                f"Recommend configuring a search provider for live research results."
            )

        source_count = len(sources)
        quality = sum(1 for s in sources if s.get("url") or s.get("doi"))
        confidence = _clamp(0.3 + (min(source_count, 10) * 0.04) + (min(quality, 5) * 0.03))

        response = "\n\n".join(response_parts) if response_parts else f"Research topic: {query}"

        return {"response": response, "confidence": confidence, "sources": sources}


# ---------------------------------------------------------------------------
# CodingAgent
# ---------------------------------------------------------------------------

class CodingAgent:
    """Handles code-related tasks across multiple programming languages."""

    name = "CodingAgent"
    description = "Provides code suggestions, explanations, debugging, and language detection."

    def _detect_language(self, text: str, context: dict = None) -> str:
        context = context or {}
        if "language" in context:
            return context["language"].lower()
        if "filename" in context:
            filename = context["filename"].lower()
            for lang, info in SUPPORTED_LANGUAGES.items():
                if any(filename.endswith(ext) for ext in info["extensions"]):
                    return lang

        lower = text.lower()
        scores: Dict[str, int] = {}
        for lang, info in SUPPORTED_LANGUAGES.items():
            scores[lang] = sum(1 for kw in info["keywords"] if re.search(r"\b" + kw + r"\b", lower))

        if max(scores.values(), default=0) > 0:
            return max(scores, key=scores.get)
        return "unknown"

    def _format_code_block(self, code: str, language: str = "") -> str:
        if language == "unknown":
            language = ""
        return f"```{language}\n{code}\n```"

    def _generate_explanation(self, query: str, language: str) -> str:
        lower = query.lower()

        if any(kw in lower for kw in ["debug", "error", "fix", "bug", "issue"]):
            return (
                f"## Debugging Assistance ({language})\n\n"
                f"Common debugging steps:\n"
                f"1. Check error messages and stack traces for the root cause\n"
                f"2. Verify input data types and null/undefined handling\n"
                f"3. Add logging or print statements to trace execution\n"
                f"4. Check for off-by-one errors, race conditions, or resource leaks\n"
                f"5. Validate assumptions with unit tests\n\n"
                f"Provide the specific error message or problematic code for targeted help."
            )

        if any(kw in lower for kw in ["explain", "what does", "how does", "understand"]):
            return (
                f"## Code Explanation ({language})\n\n"
                f"Please provide the code snippet you'd like explained. I can cover:\n"
                f"- Line-by-line walkthrough\n"
                f"- Data flow and control flow\n"
                f"- Design patterns used\n"
                f"- Potential edge cases\n"
                f"- Performance characteristics"
            )

        if any(kw in lower for kw in ["refactor", "improve", "clean", "optimize"]):
            return (
                f"## Refactoring Suggestions ({language})\n\n"
                f"Common refactoring strategies:\n"
                f"- Extract methods/functions for repeated logic\n"
                f"- Replace magic numbers with named constants\n"
                f"- Simplify conditional expressions\n"
                f"- Remove dead code and unused imports\n"
                f"- Apply SOLID principles where applicable\n\n"
                f"Share the code to receive specific refactoring recommendations."
            )

        if any(kw in lower for kw in ["suggest", "implement", "create", "build", "write"]):
            return (
                f"## Code Implementation ({language})\n\n"
                f"To provide accurate code suggestions:\n"
                f"1. Specify the function/class signature or expected behavior\n"
                f"2. Note any dependencies or frameworks in use\n"
                f"3. Mention performance or compatibility constraints\n"
                f"4. Provide example inputs and expected outputs"
            )

        return (
            f"## Coding Assistant ({language})\n\n"
            f"I can help with:\n"
            f"- **Code review** and bug identification\n"
            f"- **Writing** new functions, classes, or modules\n"
            f"- **Explaining** existing code logic\n"
            f"- **Refactoring** for clarity and performance\n"
            f"- **Debugging** errors and unexpected behavior\n"
            f"- **Best practices** for {language}\n\n"
            f"Provide more details about what you need."
        )

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        language = self._detect_language(query, context)
        explanation = self._generate_explanation(query, language)

        sources: List[Dict[str, str]] = []
        if language != "unknown":
            docs: Dict[str, str] = {
                "python": "https://docs.python.org/3/",
                "javascript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
                "typescript": "https://www.typescriptlang.org/docs/",
                "java": "https://docs.oracle.com/en/java/",
                "csharp": "https://learn.microsoft.com/dotnet/csharp/",
                "go": "https://go.dev/doc/",
                "rust": "https://doc.rust-lang.org/book/",
            }
            if language in docs:
                sources.append({"title": f"{language.title()} documentation", "url": docs[language]})

        confidence = _clamp(0.6 if language != "unknown" else 0.4)

        return {"response": explanation, "confidence": confidence, "sources": sources}


# ---------------------------------------------------------------------------
# DataAgent
# ---------------------------------------------------------------------------

class DataAgent:
    """Handles data analysis for CSV, JSON, and structured data."""

    name = "DataAgent"
    description = "Analyzes structured data, computes statistics, and suggests visualizations."

    def _parse_csv(self, text: str) -> Tuple[List[str], List[Dict[str, str]]]:
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = [row for row in reader]
        return headers, rows

    def _parse_json(self, text: str) -> Any:
        return json.loads(text)

    def _compute_column_stats(self, values: List[float]) -> Dict[str, float]:
        if not values:
            return {}
        return {
            "count": float(len(values)),
            "mean": round(mean(values), 4),
            "std": round(pstdev(values), 4) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }

    def _detect_format(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith(("{", "[")):
            try:
                json.loads(stripped)
                return "json"
            except json.JSONDecodeError:
                pass
        lines = stripped.split("\n")
        if len(lines) >= 2:
            comma_count = lines[0].count(",")
            if comma_count >= 1 and all(line.count(",") == comma_count for line in lines[:5] if line.strip()):
                return "csv"
        return "unknown"

    def _analyze_csv(self, text: str) -> Dict[str, Any]:
        headers, rows = self._parse_csv(text)
        if not headers or not rows:
            return _empty_result("No data found in CSV input.", 0.2)

        stats: Dict[str, Any] = {}
        for header in headers:
            numeric_values = []
            value_counts: List[Dict[str, Any]] = []
            for row in rows:
                val = row.get(header, "")
                try:
                    numeric_values.append(float(val))
                except (ValueError, TypeError):
                    pass
            if numeric_values and len(numeric_values) > len(rows) * 0.5:
                stats[header] = self._compute_column_stats(numeric_values)
            else:
                counter = Counter(row.get(header, "") for row in rows)
                top = counter.most_common(5)
                stats[header] = {"type": "categorical", "unique": float(len(counter)), "top_values": [{"value": v, "count": c} for v, c in top]}

        response_lines = [
            f"## Data Analysis Results",
            f"**Rows:** {len(rows)}  |  **Columns:** {len(headers)}",
            f"**Columns:** {', '.join(headers)}",
            "",
            "### Column Statistics",
        ]
        for col, col_stats in stats.items():
            response_lines.append(f"\n**{col}:**")
            if "mean" in col_stats:
                response_lines.append(f"  Mean: {col_stats['mean']}  |  Std: {col_stats['std']}  |  Range: [{col_stats['min']}, {col_stats['max']}]")
            else:
                response_lines.append(f"  Unique: {col_stats.get('unique', 0)}  |  Type: categorical")

        response_lines.extend([
            "",
            "### Suggested Visualizations",
            "- Histogram for each numeric column",
            "- Bar chart for categorical distributions",
            "- Scatter plot for numeric column pairs",
            "- Correlation heatmap",
        ])

        confidence = _clamp(0.5 + min(len(rows), 100) * 0.003 + min(len(headers), 10) * 0.02)
        return {"response": "\n".join(response_lines), "confidence": confidence, "sources": []}

    def _analyze_json(self, text: str) -> Dict[str, Any]:
        data = self._parse_json(text)
        if isinstance(data, list):
            row_count = len(data)
            if row_count > 0 and isinstance(data[0], dict):
                keys = list(data[0].keys())
                response = (
                    f"## JSON Array Analysis\n"
                    f"**Items:** {row_count}  |  **Fields:** {', '.join(keys)}\n\n"
                    f"Use the CSV analysis path for detailed statistics on tabular JSON data. "
                    f"Consider converting to CSV format for column-wise analysis."
                )
                return {"response": response, "confidence": 0.5, "sources": []}
        elif isinstance(data, dict):
            keys = list(data.keys())
            response = (
                f"## JSON Object Analysis\n"
                f"**Top-level keys ({len(keys)}):** {', '.join(keys[:20])}\n\n"
                f"Structure appears valid. Provide tabular data (array of objects) for detailed statistical analysis."
            )
            return {"response": response, "confidence": 0.4, "sources": []}

        return _empty_result("JSON parsed but no analyzable structure detected.", 0.3)

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        data_text = context.get("data", query)
        fmt = self._detect_format(data_text)

        if fmt == "csv":
            return self._analyze_csv(data_text)
        elif fmt == "json":
            return self._analyze_json(data_text)

        return {
            "response": (
                "## Data Analysis\n\n"
                "I can analyze CSV and JSON data. Please provide:\n"
                "- Pasted CSV content with headers\n"
                "- JSON array of objects\n"
                "- Or reference a file in the context\n\n"
                "Supported analyses: summary statistics, distributions, correlations, trend detection, visualization suggestions."
            ),
            "confidence": 0.3,
            "sources": [],
        }


# ---------------------------------------------------------------------------
# WritingAgent
# ---------------------------------------------------------------------------

class WritingAgent:
    """Handles writing improvement, editing, and content generation."""

    name = "WritingAgent"
    description = "Improves text quality, tone, clarity, grammar, and generates content outlines."

    def _analyze_text(self, text: str) -> Dict[str, Any]:
        word_list = text.split()
        sentence_list = re.split(r"[.!?]+", text)
        sentence_list = [s.strip() for s in sentence_list if s.strip()]
        word_count = len(word_list)
        sentence_count = max(1, len(sentence_list))
        avg_words = word_count / sentence_count

        issues: List[str] = []
        suggestions: List[str] = []

        if avg_words > 25:
            issues.append(f"Average sentence length ({avg_words:.1f} words) is high. Aim for 15-20 words.")
            suggestions.append("Break long sentences into shorter ones for clarity.")

        passive = re.findall(r"\b(is|are|was|were|be|been|being)\s+\w+ed\b", text, re.I)
        if len(passive) > sentence_count * 0.3:
            issues.append(f"High passive voice usage ({len(passive)} instances).")
            suggestions.append("Convert passive constructions to active voice.")

        repeats = re.findall(r"\b(\w+)\s+\1\b", text, re.I)
        if repeats:
            issues.append(f"Repeated words detected: {', '.join(set(repeats[:5]))}.")
            suggestions.append("Remove duplicate words.")

        filler = re.findall(r"\b(very|really|just|quite|basically|actually|literally)\b", text, re.I)
        if len(filler) > 3:
            issues.append(f"Filler words detected ({len(filler)} instances).")
            suggestions.append("Remove filler words for more concise writing.")

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) > 5 and not re.search(r"(?m)^#{1,6}\s", text):
            issues.append("Long document without headings.")
            suggestions.append("Add section headings to improve navigation.")

        return {
            "issues": issues,
            "suggestions": suggestions,
            "stats": {
                "word_count": word_count,
                "sentence_count": sentence_count,
                "avg_words_per_sentence": round(avg_words, 1),
                "paragraph_count": len(paragraphs),
            },
        }

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        text = context.get("text", query)
        task = context.get("task", "analyze").lower()
        tone = context.get("tone", "professional")

        if task == "outline":
            return self._generate_outline(query, context)
        if task == "rewrite":
            return self._suggest_rewrite(text, tone)

        analysis = self._analyze_text(text)
        lines = [
            "## Writing Analysis",
            f"**Words:** {analysis['stats']['word_count']}  |  "
            f"**Sentences:** {analysis['stats']['sentence_count']}  |  "
            f"**Avg words/sentence:** {analysis['stats']['avg_words_per_sentence']}",
            "",
        ]
        if analysis["issues"]:
            lines.append("### Issues Found")
            for issue in analysis["issues"]:
                lines.append(f"- {issue}")
            lines.append("")
        if analysis["suggestions"]:
            lines.append("### Suggestions")
            for suggestion in analysis["suggestions"]:
                lines.append(f"- {suggestion}")
        else:
            lines.append("No major issues detected. The text is well-structured.")

        confidence = _clamp(0.5 + min(analysis["stats"]["word_count"], 500) * 0.001)
        return {"response": "\n".join(lines), "confidence": confidence, "sources": []}

    def _generate_outline(self, topic: str, context: dict) -> Dict[str, Any]:
        sections = context.get("sections", 5)
        outline_lines = [f"## Content Outline: {topic}", ""]
        for i in range(1, sections + 1):
            outline_lines.append(f"### Section {i}")
            outline_lines.append(f"- Key point to cover")
            outline_lines.append(f"- Supporting evidence or examples")
            outline_lines.append(f"- Transition to next section")
            outline_lines.append("")
        outline_lines.append("### Conclusion")
        outline_lines.append("- Summary of key findings")
        outline_lines.append("- Call to action or next steps")

        return {"response": "\n".join(outline_lines), "confidence": 0.5, "sources": []}

    def _suggest_rewrite(self, text: str, tone: str) -> Dict[str, Any]:
        suggestions = [
            f"## Rewrite Suggestions (target tone: {tone})",
            "",
            "**Improvements to consider:**",
            "- Replace passive voice with active constructions",
            "- Use shorter sentences for emphasis",
            "- Replace jargon with accessible language where appropriate",
            "- Ensure consistent tense throughout",
            "- Add transition words between paragraphs",
            "",
            "Provide specific sentences or paragraphs for targeted rewrite suggestions.",
        ]
        return {"response": "\n".join(suggestions), "confidence": 0.45, "sources": []}


# ---------------------------------------------------------------------------
# BusinessAgent
# ---------------------------------------------------------------------------

class BusinessAgent:
    """Handles business analysis, market research, and strategic assessments."""

    name = "BusinessAgent"
    description = "Performs market analysis, SWOT analysis, competitive analysis, and business planning."

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        lower = query.lower()
        analysis_type = context.get("analysis_type", "general")

        if any(kw in lower for kw in ["swot", "strengths", "weaknesses"]):
            return self._swot_analysis(query, context)
        if any(kw in lower for kw in ["market", "industry", "market analysis"]):
            return self._market_analysis(query, context)
        if any(kw in lower for kw in ["competitor", "competitive", "competition"]):
            return self._competitive_analysis(query, context)
        if any(kw in lower for kw in ["business plan", "business model", "plan"]):
            return self._business_plan(query, context)

        return self._general_analysis(query, context)

    def _swot_analysis(self, query: str, context: dict) -> Dict[str, Any]:
        subject = context.get("subject", query)
        response = (
            f"## SWOT Analysis Framework\n\n"
            f"**Subject:** {subject}\n\n"
            f"### Strengths (Internal, Positive)\n"
            f"- Identify core competencies and advantages\n"
            f"- What does the organization do well?\n"
            f"- What unique resources or capabilities exist?\n\n"
            f"### Weaknesses (Internal, Negative)\n"
            f"- What areas need improvement?\n"
            f"- What resources are lacking?\n"
            f"- Where do competitors outperform?\n\n"
            f"### Opportunities (External, Positive)\n"
            f"- What market trends favor growth?\n"
            f"- What unmet needs exist?\n"
            f"- What partnerships or technologies are emerging?\n\n"
            f"### Threats (External, Negative)\n"
            f"- What are the competitive pressures?\n"
            f"- What regulatory changes are coming?\n"
            f"- What market shifts could cause disruption?\n\n"
            f"Fill in each quadrant with specific, actionable items for your context."
        )
        return {"response": response, "confidence": 0.5, "sources": []}

    def _market_analysis(self, query: str, context: dict) -> Dict[str, Any]:
        market = context.get("market", "the target market")
        response = (
            f"## Market Analysis Framework\n\n"
            f"**Market:** {market}\n\n"
            f"### Market Overview\n"
            f"- Total addressable market (TAM)\n"
            f"- Serviceable addressable market (SAM)\n"
            f"- Serviceable obtainable market (SOM)\n\n"
            f"### Customer Segmentation\n"
            f"- Demographics and psychographics\n"
            f"- Pain points and needs\n"
            f"- Buying behavior and channels\n\n"
            f"### Market Trends\n"
            f"- Growth drivers and inhibitors\n"
            f"- Technology shifts\n"
            f"- Regulatory landscape\n\n"
            f"### Sizing Estimates\n"
            f"- Provide specific numbers and projections\n"
            f"- Cite authoritative sources for each estimate"
        )
        return {"response": response, "confidence": 0.45, "sources": []}

    def _competitive_analysis(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            "## Competitive Analysis Framework\n\n"
            "### Direct Competitors\n"
            "| Competitor | Strengths | Weaknesses | Market Share |\n"
            "|------------|-----------|------------|--------------|\n"
            "|            |           |            |              |\n\n"
            "### Competitive Positioning\n"
            "- Price vs. value positioning\n"
            "- Feature comparison matrix\n"
            "- Brand perception\n\n"
            "### Barriers to Entry\n"
            "- Capital requirements\n"
            "- Technical expertise\n"
            "- Network effects\n"
            "- Switching costs\n\n"
            "### Differentiation Opportunities\n"
            "- Unique value propositions\n"
            "- Underserved segments\n"
            "- Innovation gaps"
        )
        return {"response": response, "confidence": 0.4, "sources": []}

    def _business_plan(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            "## Business Plan Outline\n\n"
            "### 1. Executive Summary\n"
            "- Mission statement\n"
            "- Problem and solution\n"
            "- Target market\n"
            "- Revenue model\n"
            "- Funding requirements\n\n"
            "### 2. Market Analysis\n"
            "- Market size and growth\n"
            "- Customer segments\n"
            "- Competitive landscape\n\n"
            "### 3. Product/Service\n"
            "- Value proposition\n"
            "- Key features and benefits\n"
            "- Development roadmap\n\n"
            "### 4. Go-to-Market Strategy\n"
            "- Pricing strategy\n"
            "- Distribution channels\n"
            "- Marketing plan\n\n"
            "### 5. Financial Projections\n"
            "- Revenue forecast\n"
            "- Cost structure\n"
            "- Break-even analysis\n"
            "- Key assumptions\n\n"
            "### 6. Team and Operations\n"
            "- Key personnel\n"
            "- Organizational structure\n"
            "- Operational requirements"
        )
        return {"response": response, "confidence": 0.45, "sources": []}

    def _general_analysis(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            f"## Business Analysis\n\n"
            f"**Query:** {query}\n\n"
            f"I can help with:\n"
            f"- **SWOT Analysis** - Strengths, weaknesses, opportunities, threats\n"
            f"- **Market Analysis** - Market size, segments, trends, sizing\n"
            f"- **Competitive Analysis** - Competitor mapping, positioning, barriers\n"
            f"- **Business Planning** - Plans, financials, go-to-market strategy\n\n"
            f"Specify the analysis type and provide context for detailed results."
        )
        return {"response": response, "confidence": 0.4, "sources": []}


# ---------------------------------------------------------------------------
# StrategyAgent
# ---------------------------------------------------------------------------

class StrategyAgent:
    """Handles planning, goal decomposition, and strategic roadmaps."""

    name = "StrategyAgent"
    description = "Decomposes goals, creates action plans, assesses risks, and generates timelines."

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        lower = query.lower()

        if any(kw in lower for kw in ["risk", "assess", "mitigate"]):
            return self._risk_assessment(query, context)
        if any(kw in lower for kw in ["timeline", "roadmap", "schedule"]):
            return self._timeline(query, context)
        if any(kw in lower for kw in ["decompose", "break down", "milestones"]):
            return self._goal_decomposition(query, context)
        if any(kw in lower for kw in ["action plan", "steps", "how to"]):
            return self._action_plan(query, context)

        return self._default_strategy(query, context)

    def _goal_decomposition(self, query: str, context: dict) -> Dict[str, Any]:
        goal = context.get("goal", query)
        depth = context.get("depth", 3)
        response_lines = [
            f"## Goal Decomposition",
            f"**Primary Goal:** {goal}",
            "",
        ]
        for level in range(1, depth + 1):
            prefix = "  " * (level - 1)
            response_lines.append(f"{prefix}### Level {level} Objectives")
            response_lines.append(f"{prefix}- Define measurable sub-objective")
            response_lines.append(f"{prefix}  - Required resources")
            response_lines.append(f"{prefix}  - Success criteria")
            response_lines.append(f"{prefix}  - Dependencies")
            response_lines.append("")

        response_lines.extend([
            "### Key Principles",
            "- Each sub-objective should be SMART (Specific, Measurable, Achievable, Relevant, Time-bound)",
            "- Identify dependencies between sub-objectives",
            "- Assign ownership and deadlines",
            "- Review and adjust regularly",
        ])
        return {"response": "\n".join(response_lines), "confidence": 0.5, "sources": []}

    def _action_plan(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            f"## Action Plan\n\n"
            f"**Objective:** {query}\n\n"
            f"### Phase 1: Preparation (Weeks 1-2)\n"
            f"1. Define scope and success criteria\n"
            f"2. Identify stakeholders and assign roles\n"
            f"3. Gather requirements and constraints\n"
            f"4. Set up tools and infrastructure\n\n"
            f"### Phase 2: Execution (Weeks 3-6)\n"
            f"5. Implement core components\n"
            f"6. Conduct reviews at each milestone\n"
            f"7. Address blockers and adjust plans\n"
            f"8. Test and validate deliverables\n\n"
            f"### Phase 3: Completion (Weeks 7-8)\n"
            f"9. Finalize and document deliverables\n"
            f"10. Conduct retrospective\n"
            f"11. Plan next iteration\n\n"
            f"Customize phases, timelines, and tasks to your specific context."
        )
        return {"response": response, "confidence": 0.45, "sources": []}

    def _risk_assessment(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            f"## Risk Assessment\n\n"
            f"**Context:** {query}\n\n"
            f"### Risk Identification Matrix\n\n"
            f"| Risk | Likelihood | Impact | Score | Mitigation |\n"
            f"|------|-----------|--------|-------|------------|\n"
            f"|      | (1-5)     | (1-5)  | (L*I) |            |\n\n"
            f"### Risk Categories\n"
            f"- **Technical** - Implementation complexity, integration, performance\n"
            f"- **Resource** - Budget, personnel, time constraints\n"
            f"- **Market** - Demand uncertainty, competition, timing\n"
            f"- **Operational** - Process gaps, dependency failures\n"
            f"- **Regulatory** - Compliance, legal, policy changes\n\n"
            f"### Mitigation Strategies\n"
            f"- Avoid: Eliminate the risk source\n"
            f"- Transfer: Share or insure against the risk\n"
            f"- Mitigate: Reduce likelihood or impact\n"
            f"- Accept: Acknowledge and monitor"
        )
        return {"response": response, "confidence": 0.4, "sources": []}

    def _timeline(self, query: str, context: dict) -> Dict[str, Any]:
        duration = context.get("duration", "8 weeks")
        response = (
            f"## Strategic Timeline\n\n"
            f"**Objective:** {query}\n"
            f"**Duration:** {duration}\n\n"
            f"### Week 1-2: Discovery & Planning\n"
            f"- [ ] Research and gather requirements\n"
            f"- [ ] Define scope and milestones\n"
            f"- [ ] Assemble team and assign ownership\n\n"
            f"### Week 3-4: Foundation\n"
            f"- [ ] Set up infrastructure\n"
            f"- [ ] Implement core components\n"
            f"- [ ] First checkpoint review\n\n"
            f"### Week 5-6: Development\n"
            f"- [ ] Build and integrate features\n"
            f"- [ ] Conduct quality reviews\n"
            f"- [ ] Mid-point assessment\n\n"
            f"### Week 7-8: Delivery\n"
            f"- [ ] Final testing and validation\n"
            f"- [ ] Documentation and handoff\n"
            f"- [ ] Retrospective and next steps\n\n"
            f"Adjust the timeline based on project complexity and team capacity."
        )
        return {"response": response, "confidence": 0.45, "sources": []}

    def _default_strategy(self, query: str, context: dict) -> Dict[str, Any]:
        response = (
            f"## Strategy Assistant\n\n"
            f"**Query:** {query}\n\n"
            f"I can help with:\n"
            f"- **Goal Decomposition** - Break complex goals into actionable sub-objectives\n"
            f"- **Action Plans** - Step-by-step implementation plans\n"
            f"- **Risk Assessment** - Identify and mitigate risks\n"
            f"- **Timeline Generation** - Project schedules and milestones\n\n"
            f"Provide your goal or challenge for structured strategic guidance."
        )
        return {"response": response, "confidence": 0.4, "sources": []}


# ---------------------------------------------------------------------------
# ExecutiveAgent (coordinator)
# ---------------------------------------------------------------------------

class ExecutiveAgent:
    """Coordinates all specialist agents and provides unified responses."""

    name = "ExecutiveAgent"
    description = "Routes queries to specialists and combines multi-agent results."

    def __init__(self, registry: "AgentRegistry" = None):
        self._registry = registry

    def process(self, query: str, context: dict = None) -> Dict[str, Any]:
        context = context or {}
        registry = self._registry or AgentRegistry()

        target = registry.route_query(query)
        if target and target != "executive":
            agent = registry.get_agent(target)
            if agent:
                return agent.process(query, context)

        results: List[Dict[str, Any]] = []
        for name in ["research", "coding", "data", "writing", "business", "strategy"]:
            agent = registry.get_agent(name)
            if agent:
                try:
                    result = agent.process(query, context)
                    if result.get("confidence", 0) > 0.4:
                        results.append({"agent": name, **result})
                except Exception:
                    pass

        if not results:
            return _empty_result(
                "No specialist agent matched this query with sufficient confidence. "
                "Try rephrasing or specifying the task type.",
                0.2,
            )

        combined_response = "\n\n---\n\n".join(
            f"### {r['agent'].title()} Agent\n{r['response']}" for r in results
        )
        avg_confidence = mean(r["confidence"] for r in results)
        all_sources: List[Dict[str, str]] = []
        for r in results:
            all_sources.extend(r.get("sources", []))

        return {
            "response": combined_response,
            "confidence": _clamp(avg_confidence),
            "sources": all_sources,
        }


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

class AgentRegistry:
    """Central registry for discovering and routing to specialist agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, Any] = {
            "research": ResearchAgent(),
            "coding": CodingAgent(),
            "data": DataAgent(),
            "writing": WritingAgent(),
            "business": BusinessAgent(),
            "strategy": StrategyAgent(),
        }
        self._executive = ExecutiveAgent(self)
        self._agents["executive"] = self._executive

    def get_agent(self, name: str) -> Optional[Any]:
        return self._agents.get(name.lower())

    def list_agents(self) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        for key, agent in self._agents.items():
            result.append({
                "name": key,
                "class": agent.__class__.__name__,
                "description": getattr(agent, "description", ""),
            })
        return result

    def route_query(self, query: str) -> str:
        lower = query.lower()
        scores: Dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in lower)
        if not scores or max(scores.values()) == 0:
            return "executive"
        return max(scores, key=scores.get)
