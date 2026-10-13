"""Load text from many sources (URL, PDF, local file, raw text) and chunk it."""

from __future__ import annotations

import html
import re
from io import BytesIO
from pathlib import Path

import httpx

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n\s*\n\s*\n+")
_SPACES_RE = re.compile(r"[ \t]+")


def extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def html_to_text(markup: str) -> str:
    """Convert raw HTML to readable text (drops scripts/styles, unescapes entities)."""
    markup = _SCRIPT_RE.sub(" ", markup)
    markup = _TAG_RE.sub(" ", markup)
    markup = html.unescape(markup)
    markup = _SPACES_RE.sub(" ", markup)
    return _BLANK_LINES_RE.sub("\n\n", markup).strip()


def _looks_like_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


async def load_text(source: str, *, timeout: float = 60.0) -> str:
    """Resolve *source* to plain text.

    Accepts an http(s) URL, a local file path (PDF or text), or raw text.
    """
    if _looks_like_url(source):
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(source)
            response.raise_for_status()
            body = response.content
            content_type = response.headers.get("content-type", "")
        if "application/pdf" in content_type or source.lower().endswith(".pdf"):
            return extract_pdf(body)
        text = body.decode("utf-8", errors="ignore")
        if "html" in content_type.lower():
            return html_to_text(text)
        return text

    path = Path(source)
    # A raw text blob (e.g. an email or a long document) may not be a valid path.
    # On Linux, stat() on such a source raises OSError (ENAMETOOLONG, embedded
    # null, ...) instead of simply returning False, so guard the probe.
    try:
        is_file = path.exists() and path.is_file()
    except (OSError, ValueError):
        is_file = False
    if is_file:
        data = path.read_bytes()
        if path.suffix.lower() == ".pdf" or data[:4] == b"%PDF":
            return extract_pdf(data)
        return data.decode("utf-8", errors="ignore")

    return source


def chunk_text(text: str, *, size: int = 900, overlap: int = 150) -> list[str]:
    """Split *text* into overlapping character windows, preferring whitespace breaks."""
    text = text.strip()
    if not text:
        return []
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            boundary = text.rfind(" ", start + overlap, end)
            if boundary != -1:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = end - overlap
    return chunks
