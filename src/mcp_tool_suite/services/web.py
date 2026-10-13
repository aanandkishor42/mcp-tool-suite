"""Web search providers used by the web-research tool.

A provider is swappable: ``DuckDuckGoSearch`` needs no API key, ``NullSearch``
disables the network entirely (used in tests and offline demos).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

_USER_AGENT = "Mozilla/5.0 (compatible; McpToolSuite/0.1; +https://example.com)"
_ANCHOR_RE = re.compile(r'<a\b[^>]*class="result__a"[^>]*>.*?</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'<a\b[^>]*class="result__snippet"[^>]*>.*?</a>', re.DOTALL)
_HREF_RE = re.compile(r'href="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


def _strip_tags(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", fragment)).strip()


def _clean_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlsplit(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return uddg[0]
    return url


class DuckDuckGoSearch:
    name = "duckduckgo"

    def __init__(self, *, timeout: float = 20.0, base_url: str = "https://html.duckduckgo.com/html/") -> None:
        self.timeout = timeout
        self.base_url = base_url

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(
                self.base_url,
                data={"q": query, "kl": "us-en"},
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
            markup = response.text

        anchors = _ANCHOR_RE.findall(markup)
        snippets = _SNIPPET_RE.findall(markup)
        results: list[SearchResult] = []
        for i, anchor in enumerate(anchors):
            href = _HREF_RE.search(anchor)
            if not href:
                continue
            title = _strip_tags(anchor)
            snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
            results.append(SearchResult(title=title, url=_clean_url(href.group(1)), snippet=snippet))
            if len(results) >= max_results:
                break
        return results


class NullSearch:
    name = "none"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return []
