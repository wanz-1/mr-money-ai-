"""Web search capabilities using DuckDuckGo HTML search.

No API keys required. Uses urllib for HTTP requests and regex for HTML parsing.

Environment variables:
  HP_SEARCH_TIMEOUT  - Request timeout in seconds (default: 10)
  HP_SEARCH_AGENT    - User-Agent string for requests
"""

from __future__ import annotations

from .config import load_env
load_env()

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


TIMEOUT = int(_env("HP_SEARCH_TIMEOUT", "10"))
USER_AGENT = _env(
    "HP_SEARCH_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
DDG_URL = "https://html.duckduckgo.com/html/"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single search result from DuckDuckGo."""

    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>", re.S)
_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript).*?>.*?</\1>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_BLOCK_RE = re.compile(r"(?i)</(p|div|section|article|h[1-6]|li|tr|td|th|blockquote)>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _html_to_text(html: str) -> str:
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    html = _BR_RE.sub("\n", html)
    html = _BLOCK_RE.sub("\n", html)
    html = _TAG_RE.sub(" ", html)
    html = _WHITESPACE_RE.sub(" ", html)
    return unescape(html).strip()


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _MULTI_NEWLINE_RE.sub("\n\n", text).strip()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(url: str, data: Optional[bytes] = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Core search
# ---------------------------------------------------------------------------

_RESULT_BLOCK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.S,
)
_LINK_RE = re.compile(r'uddg=([^&"]+)')
_SNIPPET_TEXT_RE = re.compile(r"<[^>]+>")


def web_search(query: str, max_results: int = 5) -> List[SearchResult]:
    """Perform a web search using DuckDuckGo HTML endpoint.

    Returns up to *max_results* :class:`SearchResult` objects sorted by
    relevance.  Returns an empty list on failure instead of raising.
    """
    params = urllib.parse.urlencode({"q": query})
    url = f"{DDG_URL}?{params}"

    try:
        raw = _request(url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"[search] request failed for query '{query}': {exc}")
        return []

    html = raw.decode("utf-8", errors="replace")
    results: List[SearchResult] = []

    for match in _RESULT_BLOCK_RE.finditer(html):
        raw_href = match.group(1)
        title_html = match.group(2)
        snippet_html = match.group(3)

        m_link = _LINK_RE.search(raw_href)
        href = urllib.parse.unquote(m_link.group(1)) if m_link else raw_href
        if not href.startswith("http"):
            continue

        title = _SNIPPET_TEXT_RE.sub("", title_html).strip()
        title = unescape(title)
        snippet = _SNIPPET_TEXT_RE.sub("", snippet_html).strip()
        snippet = unescape(snippet)

        if title or snippet:
            results.append(SearchResult(title=title, url=href, snippet=snippet))

    return results[:max_results]


# ---------------------------------------------------------------------------
# Page fetching
# ---------------------------------------------------------------------------

def fetch_page(url: str, max_chars: int = 5000) -> str:
    """Fetch a URL and return stripped text content.

    HTML tags, scripts, and styles are removed.  The result is truncated to
    *max_chars* characters.  Returns an empty string on failure.
    """
    try:
        raw = _request(url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"[search] failed to fetch '{url}': {exc}")
        return ""

    html = raw.decode("utf-8", errors="replace")
    text = _html_to_text(html)
    text = _normalize(text)

    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"

    return text


# ---------------------------------------------------------------------------
# Research helpers
# ---------------------------------------------------------------------------

def summarize_sources(results: List[SearchResult], context: str = "") -> str:
    """Create a plain-text summary from a list of search results.

    Returns a human-readable string suitable for passing to an LLM prompt.
    """
    if not results:
        return "No sources found."

    parts: List[str] = []
    if context:
        parts.append(f"Research context: {context}")
        parts.append("")

    for i, r in enumerate(results, 1):
        parts.append(f"[{i}] {r.title}")
        parts.append(f"    URL:   {r.url}")
        if r.snippet:
            parts.append(f"    Snippet: {r.snippet}")
        parts.append("")

    return "\n".join(parts).strip()


def research_topic(topic: str, depth: int = 3) -> Dict[str, object]:
    """Research a topic by searching and fetching top results.

    Returns a dictionary with keys:
      - topic: the original query
      - results: list of :class:`SearchResult` dicts
      - page_texts: dict mapping URL to fetched text (up to *depth* pages)
      - summary: combined text summary
      - sources_count: total number of results found
    """
    results = web_search(topic, max_results=max(depth + 2, 5))

    page_texts: Dict[str, str] = {}
    for r in results[:depth]:
        text = fetch_page(r.url)
        if text:
            page_texts[r.url] = text

    summary = summarize_sources(results, context=topic)

    return {
        "topic": topic,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ],
        "page_texts": page_texts,
        "summary": summary,
        "sources_count": len(results),
    }
