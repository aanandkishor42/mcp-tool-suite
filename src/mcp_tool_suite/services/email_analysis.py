"""Email parsing and triage with the standard library only (no third-party deps).

Parses raw ``.eml`` messages and mbox-style mailboxes, extracts headers and a
readable text body, and heuristically pulls out action items. The LLM layer then
summarizes the mailbox or consolidates the checklist; this offline pass is what
makes the assistant more than a prompt wrapper.
"""

from __future__ import annotations

import email
import re
from email.header import decode_header, make_header
from email.message import Message

from mcp_tool_suite.services.documents import html_to_text

_MBOX_SEP = re.compile(r"(?m)^From .*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_ACTION_ITEMS = 50
_MAX_BODY_PREVIEW = 2000

# Phrases that tend to introduce a request or a commitment.
_ACTION_CUES = (
    "please",
    "can you",
    "could you",
    "can we",
    "could we",
    "need to",
    "needs to",
    "needed",
    "should",
    "must",
    "action item",
    "action:",
    "todo",
    "to-do",
    "follow up",
    "follow-up",
    "followup",
    "make sure",
    "remember to",
    "don't forget",
    "dont forget",
    "deadline",
    "due by",
    "by friday",
    "by monday",
    "by tuesday",
    "by wednesday",
    "by thursday",
    "asap",
)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # malformed header encodings must not break parsing
        return str(value)


def _text_body(msg: Message) -> str:
    if msg.is_multipart():
        plain: list[str] = []
        html: list[str] = []
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or ""):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
            ctype = part.get_content_type()
            if ctype == "text/plain":
                plain.append(text)
            elif ctype == "text/html":
                html.append(text)
        if plain:
            return "\n".join(plain)
        if html:
            return html_to_text("\n".join(html))
        return ""

    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload() or "")
    charset = msg.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="ignore")
    if msg.get_content_type() == "text/html":
        return html_to_text(text)
    return text


def parse_message(raw: str) -> dict[str, object]:
    """Parse a single RFC 822 message into a JSON-friendly dict."""
    msg = email.message_from_string(raw)
    body = _text_body(msg).strip()
    return {
        "from": _decode(msg.get("From")),
        "to": _decode(msg.get("To")),
        "subject": _decode(msg.get("Subject")),
        "date": _decode(msg.get("Date")),
        "body": body,
        "characters": len(body),
    }


def parse_mailbox(raw: str) -> list[dict[str, object]]:
    """Parse raw text as one or more messages (mbox separators or a single email)."""
    raw = (raw or "").strip()
    if not raw:
        return []

    matches = list(_MBOX_SEP.finditer(raw))
    if not matches:
        return [parse_message(raw)]

    messages: list[dict[str, object]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chunk = raw[start:end].strip()
        if chunk:
            messages.append(parse_message(chunk))
    return messages or [parse_message(raw)]


def mailbox_summary(messages: list[dict[str, object]]) -> dict[str, object]:
    """Count messages, rank senders and collect subjects/dates."""
    senders: dict[str, int] = {}
    for message in messages:
        sender = str(message.get("from") or "(unknown)")
        senders[sender] = senders.get(sender, 0) + 1
    ranked = sorted(senders.items(), key=lambda kv: (-kv[1], kv[0]))
    dates = [str(m["date"]) for m in messages if m.get("date")]
    return {
        "count": len(messages),
        "senders": [{"value": name, "count": count} for name, count in ranked[:10]],
        "subjects": [str(m.get("subject") or "") for m in messages],
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }


def _sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    cleaned: list[str] = []
    for part in parts:
        stripped = part.strip().strip("-*\u2022 ").strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def extract_action_items(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    """Heuristically pull action items and open questions out of message bodies."""
    items: list[dict[str, object]] = []
    for message in messages:
        subject = str(message.get("subject") or "")
        body = str(message.get("body") or "")
        for sentence in _sentences(body):
            if sentence.startswith(">"):
                continue
            lowered = sentence.lower()
            cues = [cue for cue in _ACTION_CUES if cue in lowered]
            if cues:
                items.append(
                    {"text": sentence, "subject": subject, "cues": cues, "kind": "action"}
                )
            elif sentence.endswith("?") and len(sentence) > 12:
                items.append(
                    {"text": sentence, "subject": subject, "cues": [], "kind": "question"}
                )
            if len(items) >= _MAX_ACTION_ITEMS:
                return items
    return items


def message_headers(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return compact per-message headers (with a short body preview)."""
    return [
        {
            "from": m.get("from", ""),
            "to": m.get("to", ""),
            "subject": m.get("subject", ""),
            "date": m.get("date", ""),
            "characters": m.get("characters", 0),
            "preview": str(m.get("body") or "")[:_MAX_BODY_PREVIEW],
        }
        for m in messages
    ]
