"""AI Assistant module for HumanProof AI.

Multi-provider intelligent assistant with OpenAI, Anthropic, custom, and local fallback.
Environment variables:
  HP_AI_PROVIDER      - "openai" | "anthropic" | "custom" | "local" (default: auto-detect)
  HP_OPENAI_API_KEY   - OpenAI API key
  HP_OPENAI_MODEL     - Model name (default: gpt-4o)
  HP_ANTHROPIC_API_KEY - Anthropic API key
  HP_ANTHROPIC_MODEL  - Model name (default: claude-sonnet-4-20250514)
  HP_CUSTOM_API_BASE  - Custom API base URL (OpenAI-compatible)
  HP_CUSTOM_API_KEY   - Custom API key
  HP_CUSTOM_MODEL     - Custom model name (default: dev-x)
  HP_AI_MAX_TOKENS    - Max response tokens (default: 4096)
  HP_AI_TEMPERATURE   - Temperature (default: 0.7)
"""

from __future__ import annotations

from .config import load_env
load_env()

import json
import os
import uuid
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .models import Document, DocumentMetadata, utc_now
from .orchestrator import review_document


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


PROVIDER = _env("HP_AI_PROVIDER", "").lower()
OPENAI_API_KEY = _env("HP_OPENAI_API_KEY")
OPENAI_MODEL = _env("HP_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_API_KEY = _env("HP_ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("HP_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
CUSTOM_API_BASE = _env("HP_CUSTOM_API_BASE")
CUSTOM_API_KEY = _env("HP_CUSTOM_API_KEY")
CUSTOM_MODEL = _env("HP_CUSTOM_MODEL", "dev-x")
MAX_TOKENS = int(_env("HP_AI_MAX_TOKENS", "4096"))
TEMPERATURE = float(_env("HP_AI_TEMPERATURE", "0.7"))


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the HumanProof AI Assistant, an expert in document analysis, writing quality, and publication readiness. You work inside the HumanProof AI platform.

Your capabilities:
- Analyze writing quality, grammar, style, readability, and tone
- Review documents for citation accuracy, accessibility, and compliance
- Provide actionable recommendations for improving documents
- Explain AI-writing analysis findings in plain language
- Help users understand review scores, findings, and action plans
- Assist with document comparison, formatting, and structuring
- Answer questions about best practices for academic, professional, and public-facing writing

Guidelines:
- Be concise but thorough. Prioritize actionable advice.
- Reference specific scores, findings, or metrics when discussing a document.
- When context includes document text or review results, ground your answers in that data.
- If you're unsure, say so honestly rather than speculating.
- Always remind users that AI analysis is decision support, not definitive proof.
- Format responses with clear structure: headings, bullet points, and numbered lists where helpful."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=utc_now)


@dataclass
class ChatSession:
    session_id: str
    created_at: str
    messages: List[ChatMessage] = field(default_factory=list)
    document_context: Optional[str] = None
    document_name: Optional[str] = None
    review_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "createdAt": self.created_at,
            "messages": [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in self.messages],
            "documentName": self.document_name,
            "hasReviewContext": self.review_context is not None,
        }


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

SESSIONS: Dict[str, ChatSession] = {}


def create_session(
    document_text: Optional[str] = None,
    document_name: Optional[str] = None,
    review_data: Optional[Dict[str, Any]] = None,
) -> ChatSession:
    session_id = str(uuid.uuid4())
    session = ChatSession(
        session_id=session_id,
        created_at=utc_now(),
        document_context=document_text[:50000] if document_text else None,
        document_name=document_name,
        review_context=review_data,
    )
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> Optional[ChatSession]:
    return SESSIONS.get(session_id)


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _build_messages(session: ChatSession, user_message: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    for msg in session.messages[-20:]:
        messages.append({"role": msg.role, "content": msg.content})

    context_prefix = ""
    if session.document_context:
        preview = session.document_context[:8000]
        context_prefix = (
            f"[DOCUMENT: {session.document_name or 'untitled'}]\n"
            f"{preview}\n"
            f"[END DOCUMENT]\n\n"
        )

    if session.review_context:
        review_summary = _summarize_review(session.review_context)
        context_prefix += f"[REVIEW RESULTS]\n{review_summary}\n[END REVIEW]\n\n"

    messages.append({"role": "user", "content": context_prefix + user_message})
    return messages


def _summarize_review(review: Dict[str, Any]) -> str:
    lines: List[str] = []
    if "summary" in review:
        lines.append(f"Summary: {review['summary']}")
    if "scores" in review:
        score_lines = [f"  {k}: {v}" for k, v in review["scores"].items()]
        lines.append("Scores:\n" + "\n".join(score_lines))
    if "findings" in review:
        count = len(review["findings"])
        high = sum(1 for f in review["findings"] if f.get("severity") in ("high", "critical"))
        lines.append(f"Findings: {count} total, {high} high-priority")
    if "actionPlan" in review:
        plan = review["actionPlan"][:5]
        lines.append("Top action items:\n" + "\n".join(f"  - {item}" for item in plan))
    return "\n".join(lines) if lines else "No review data available."


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _detect_provider() -> str:
    if PROVIDER:
        return PROVIDER
    if CUSTOM_API_KEY and CUSTOM_API_BASE:
        return "custom"
    if OPENAI_API_KEY:
        return "openai"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return "local"


def chat(session_id: str, user_message: str) -> Dict[str, Any]:
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found."}

    if not user_message.strip():
        return {"error": "Empty message."}

    provider = _detect_provider()
    messages = _build_messages(session, user_message)

    session.messages.append(ChatMessage(role="user", content=user_message))

    try:
        if provider == "openai":
            reply = _chat_openai(messages)
        elif provider == "anthropic":
            reply = _chat_anthropic(messages)
        elif provider == "custom":
            reply = _chat_custom(messages)
        else:
            reply = _chat_local(session, user_message)
    except Exception as exc:
        reply = f"I encountered an error connecting to the AI provider ({provider}): {exc}. Please check your API key configuration or try the local mode."

    session.messages.append(ChatMessage(role="assistant", content=reply))

    return {
        "reply": reply,
        "provider": provider,
        "sessionId": session_id,
    }


def _chat_openai(messages: List[Dict[str, str]]) -> str:
    if not OPENAI_API_KEY:
        return "OpenAI API key not configured. Set HP_OPENAI_API_KEY environment variable."

    payload = json.dumps({
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "No response generated.")
    return "No response from OpenAI."


def _chat_anthropic(messages: List[Dict[str, str]]) -> str:
    if not ANTHROPIC_API_KEY:
        return "Anthropic API key not configured. Set HP_ANTHROPIC_API_KEY environment variable."

    system_msg = ""
    api_messages: List[Dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg += msg["content"] + "\n\n"
        else:
            api_messages.append(msg)

    payload = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_msg.strip(),
        "messages": api_messages,
        "temperature": TEMPERATURE,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data.get("content", [])
    if content:
        return content[0].get("text", "No response generated.")
    return "No response from Anthropic."


def _chat_custom(messages: List[Dict[str, str]]) -> str:
    if not CUSTOM_API_KEY or not CUSTOM_API_BASE:
        return "Custom API not configured. Set HP_CUSTOM_API_BASE and HP_CUSTOM_API_KEY."

    url = CUSTOM_API_BASE.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": CUSTOM_MODEL,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CUSTOM_API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "No response generated.")
    return "No response from custom provider."


def _chat_local(session: ChatSession, user_message: str) -> str:
    lower = user_message.lower().strip()

    if any(kw in lower for kw in ["help", "what can you do", "capabilities", "features"]):
        return (
            "I'm the HumanProof AI Assistant running in local mode. Here's what I can help with:\n\n"
            "**Document Analysis** - I can analyze documents you paste into the review workspace.\n"
            "**Review Interpretation** - Ask me to explain any finding, score, or recommendation.\n"
            "**Writing Advice** - Get suggestions on grammar, style, tone, readability, and structure.\n"
            "**Best Practices** - Learn about citation styles, accessibility, compliance, and more.\n\n"
            "For full AI-powered chat with deeper analysis, configure an OpenAI or Anthropic API key:\n"
            "- `HP_OPENAI_API_KEY` for GPT-4o\n"
            "- `HP_ANTHROPIC_API_KEY` for Claude"
        )

    if any(kw in lower for kw in ["review", "analyze", "score", "assess"]):
        if session.document_context:
            report = review_document(Document(
                text=session.document_context,
                metadata=DocumentMetadata(filename=session.document_name or "document.txt"),
            ))
            lines = [
                f"## Review of {session.document_name or 'your document'}",
                f"\n**Publication Readiness:** {report.scores.get('publication_readiness', 0):.1f}/100",
                f"**Summary:** {report.summary}",
                "\n### Key Scores",
            ]
            for k, v in report.scores.items():
                if k in ("publication_readiness", "writing_quality", "grammar", "readability", "originality"):
                    lines.append(f"- **{k.replace('_', ' ').title()}:** {v:.1f}")
            if report.findings:
                high_findings = [f for f in report.findings if f.severity in ("high", "critical")]
                lines.append(f"\n### Findings ({len(report.findings)} total, {len(high_findings)} high-priority)")
                for f in report.findings[:5]:
                    lines.append(f"- [{f.severity.upper()}] {f.title}: {f.recommendation}")
            if report.action_plan:
                lines.append("\n### Action Plan")
                for item in report.action_plan[:5]:
                    lines.append(f"1. {item}")
            return "\n".join(lines)
        return (
            "To analyze a document, please provide the document text in the chat, or load a document "
            "in the Review workspace first. Then ask me to review it."
        )

    if any(kw in lower for kw in ["grammar", "spelling", "typo", "error"]):
        return (
            "For grammar and spelling analysis, the best approach is:\n\n"
            "1. Paste your document text in the **Review** workspace\n"
            "2. Click **Run Review** to get a full grammar analysis\n"
            "3. Ask me here about any specific findings\n\n"
            "The Grammar Agent checks for subject-verb agreement, tense consistency, "
            "comma splices, run-on sentences, passive voice overuse, and common misspellings."
        )

    if any(kw in lower for kw in ["citation", "reference", "bibliography", "apa", "mla", "chicago"]):
        return (
            "**Citation Best Practices:**\n\n"
            "- **APA 7th Edition:** Author, A. A. (Year). Title. Publisher. DOI\n"
            "- **MLA 9th Edition:** Author. Title. Publisher, Year.\n"
            "- **Chicago:** Author. Title. Place: Publisher, Year.\n\n"
            "Common issues to check:\n"
            "- In-text citation matches reference list\n"
            "- DOIs included where available\n"
            "- Consistent formatting throughout\n"
            "- Proper capitalization in titles\n\n"
            "Use the **Research Intelligence** page for citation validation and style conversion."
        )

    if any(kw in lower for kw in ["readability", "reading level", "grade level", "flesch"]):
        return (
            "**Readability Analysis:**\n\n"
            "The Readability Agent evaluates:\n"
            "- Flesch-Kincaid Grade Level\n"
            "- Average sentence length\n"
            "- Complex word density\n"
            "- Paragraph structure and flow\n\n"
            "**Tips to improve readability:**\n"
            "1. Break long sentences (aim for 15-20 words avg)\n"
            "2. Use active voice where possible\n"
            "3. Replace jargon with plain language\n"
            "4. Add transition words between paragraphs\n"
            "5. Use headings and subheadings for structure"
        )

    if any(kw in lower for kw in ["ai writing", "ai generated", "chatgpt", "artificial"]):
        return (
            "**About AI-Writing Analysis:**\n\n"
            "The Transparent AI-Writing Analysis Agent provides probabilistic estimates, not proof. "
            "It looks at:\n"
            "- Vocabulary diversity and predictability\n"
            "- Sentence structure uniformity\n"
            "- Perplexity and burstiness patterns\n"
            "- Statistical markers compared to known human and AI patterns\n\n"
            "**Important:** These are decision support indicators. AI analysis must not be used as "
            "the sole basis for academic integrity or misconduct determinations."
        )

    if any(kw in lower for kw in ["accessibility", "wcag", "screen reader", "a11y"]):
        return (
            "**Document Accessibility Checklist:**\n\n"
            "- Use proper heading hierarchy (H1 > H2 > H3)\n"
            "- Provide alt text for images\n"
            "- Use descriptive link text (not 'click here')\n"
            "- Ensure sufficient color contrast\n"
            "- Use lists for sequential or grouped content\n"
            "- Include a document language declaration\n"
            "- Use table headers for data tables\n"
            "- Avoid relying solely on color to convey meaning"
        )

    return (
        f"I'm running in **local mode** (no external AI API configured). "
        "I can help you understand review findings, scores, and writing best practices.\n\n"
        "Try asking me about:\n"
        "- Grammar and spelling\n"
        "- Readability improvement\n"
        "- Citation formatting\n"
        "- AI-writing analysis\n"
        "- Accessibility compliance\n"
        "- Writing best practices\n\n"
        "For deeper conversational AI, set `HP_OPENAI_API_KEY` or `HP_ANTHROPIC_API_KEY`."
    )


# ---------------------------------------------------------------------------
# Provider info
# ---------------------------------------------------------------------------

def get_provider_info() -> Dict[str, Any]:
    active = _detect_provider()
    return {
        "active": active,
        "providers": {
            "openai": {
                "configured": bool(OPENAI_API_KEY),
                "model": OPENAI_MODEL,
            },
            "anthropic": {
                "configured": bool(ANTHROPIC_API_KEY),
                "model": ANTHROPIC_MODEL,
            },
            "custom": {
                "configured": bool(CUSTOM_API_KEY and CUSTOM_API_BASE),
                "model": CUSTOM_MODEL,
                "baseUrl": CUSTOM_API_BASE,
            },
            "local": {
                "configured": True,
                "description": "Built-in assistant using HumanProof AI review agents",
            },
        },
    }


# ---------------------------------------------------------------------------
# SSE Streaming
# ---------------------------------------------------------------------------

def chat_stream(session_id: str, user_message: str):
    """Yields SSE events: data: {"token": "..."} or data: {"done": true, "fullReply": "..."}"""
    session = get_session(session_id)
    if not session:
        yield f"data: {json.dumps({'error': 'Session not found.'})}\n\n"
        return

    if not user_message.strip():
        yield f"data: {json.dumps({'error': 'Empty message.'})}\n\n"
        return

    provider = _detect_provider()
    messages = _build_messages(session, user_message)
    session.messages.append(ChatMessage(role="user", content=user_message))

    full_reply = ""

    try:
        if provider in ("openai", "custom"):
            for token in _stream_openai_compatible(messages, provider):
                full_reply += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        elif provider == "anthropic":
            for token in _stream_anthropic(messages):
                full_reply += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        else:
            reply = _chat_local(session, user_message)
            full_reply = reply
            yield f"data: {json.dumps({'token': reply})}\n\n"
    except Exception as exc:
        full_reply = f"Stream error ({provider}): {exc}"
        yield f"data: {json.dumps({'token': full_reply})}\n\n"

    session.messages.append(ChatMessage(role="assistant", content=full_reply))
    yield f"data: {json.dumps({'done': True, 'fullReply': full_reply, 'provider': provider, 'sessionId': session_id})}\n\n"


def _stream_openai_compatible(messages: List[Dict[str, str]], provider: str):
    """Yields tokens from OpenAI-compatible streaming API."""
    if provider == "custom":
        api_base = CUSTOM_API_BASE
        api_key = CUSTOM_API_KEY
        model = CUSTOM_MODEL
    else:
        api_base = "https://api.openai.com/v1"
        api_key = OPENAI_API_KEY
        model = OPENAI_MODEL

    if not api_key:
        yield "API key not configured."
        return

    url = api_base.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        buffer = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass


def _stream_anthropic(messages: List[Dict[str, str]]):
    """Yields tokens from Anthropic streaming API."""
    if not ANTHROPIC_API_KEY:
        yield "Anthropic API key not configured."
        return

    system_msg = ""
    api_messages: List[Dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg += msg["content"] + "\n\n"
        else:
            api_messages.append(msg)

    payload = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_msg.strip(),
        "messages": api_messages,
        "temperature": TEMPERATURE,
        "stream": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        buffer = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    pass


# ---------------------------------------------------------------------------
# Image Generation
# ---------------------------------------------------------------------------

IMAGE_GEN_MODEL = "image-gen"


def generate_image(prompt: str, size: str = "1024x1024", n: int = 1) -> Dict[str, Any]:
    """Generate an image using the custom API."""
    if not CUSTOM_API_KEY or not CUSTOM_API_BASE:
        return {"error": "Image generation requires a configured custom API."}

    url = CUSTOM_API_BASE.rstrip("/") + "/images/generations"
    payload = json.dumps({
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "n": n,
        "size": size,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CUSTOM_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        images = data.get("data", [])
        if images:
            return {
                "images": [{"url": img.get("url", ""), "revisedPrompt": img.get("revised_prompt", "")} for img in images],
                "provider": "custom",
            }
        return {"error": "No images generated."}
    except Exception as exc:
        return {"error": f"Image generation failed: {exc}"}
