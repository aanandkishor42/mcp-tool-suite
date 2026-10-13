from __future__ import annotations

import asyncio

from mcp_tool_suite.context import build_context
from mcp_tool_suite.registry import ToolRegistry
from mcp_tool_suite.services.email_analysis import (
    extract_action_items,
    mailbox_summary,
    parse_mailbox,
    parse_message,
)
from mcp_tool_suite.tools import EmailAssistantTool, default_plugins

_EMAIL = (
    "From: Priya <priya@example.com>\n"
    "To: Team <team@example.com>\n"
    "Subject: Launch checklist\n"
    "Date: Mon, 3 Mar 2025 09:15:00 +0000\n"
    "\n"
    "Hi team,\n"
    "Please send the release notes by Friday.\n"
    "We should review the pricing page before launch.\n"
    "Can you schedule a dry run next week?\n"
    "Thanks,\n"
    "Priya\n"
)

_MBOX = (
    "From alice@example.com Mon Mar 3 09:00:00 2025\n"
    "From: Alice <alice@example.com>\n"
    "Subject: One\n"
    "\n"
    "Body one.\n"
    "\n"
    "From bob@example.com Mon Mar 3 10:00:00 2025\n"
    "From: Bob <bob@example.com>\n"
    "Subject: Two\n"
    "\n"
    "Body two.\n"
)


def test_parse_single_message():
    parsed = parse_message(_EMAIL)
    assert parsed["from"] == "Priya <priya@example.com>"
    assert parsed["subject"] == "Launch checklist"
    assert "release notes" in parsed["body"]
    assert parsed["characters"] > 0


def test_parse_mbox_multiple_messages():
    messages = parse_mailbox(_MBOX)
    assert len(messages) == 2
    assert messages[0]["subject"] == "One"
    assert messages[1]["subject"] == "Two"


def test_extract_action_items_finds_requests_and_questions():
    messages = parse_mailbox(_EMAIL)
    items = extract_action_items(messages)
    texts = " ".join(item["text"] for item in items).lower()
    assert "release notes" in texts
    assert "pricing page" in texts
    assert "dry run" in texts
    assert all(item["kind"] in {"action", "question"} for item in items)


def test_mailbox_summary_ranks_senders():
    summary = mailbox_summary(parse_mailbox(_MBOX))
    assert summary["count"] == 2
    assert {s["value"] for s in summary["senders"]} == {
        "Alice <alice@example.com>",
        "Bob <bob@example.com>",
    }


def test_email_assistant_is_registered():
    names = ToolRegistry(default_plugins()).names()
    assert "email_assistant" in names
    assert any(isinstance(p, EmailAssistantTool) for p in default_plugins())


def test_email_assistant_summarize_offline(settings):
    ctx = build_context(settings)
    fn = EmailAssistantTool().create(ctx)
    out = asyncio.run(fn(source=_EMAIL, action="summarize"))
    assert out["action"] == "summarize"
    assert len(out["messages"]) == 1
    assert out["stats"]["count"] == 1
    assert out["summary"]


def test_email_assistant_extract_actions_offline(settings):
    ctx = build_context(settings)
    fn = EmailAssistantTool().create(ctx)
    out = asyncio.run(fn(source=_EMAIL, action="extract_actions"))
    assert out["action"] == "extract_actions"
    texts = " ".join(item["text"] for item in out["action_items"]).lower()
    assert "release notes" in texts
    assert out["summary"]


def test_email_assistant_draft_offline(settings):
    ctx = build_context(settings)
    fn = EmailAssistantTool().create(ctx)
    out = asyncio.run(
        fn(
            action="draft",
            instruction="Tell the client the invoice is attached.",
            recipient="client@example.com",
            tone="friendly",
        )
    )
    assert out["action"] == "draft"
    assert out["recipient"] == "client@example.com"
    assert out["subject"]
    assert out["body"]


def test_email_assistant_draft_requires_instruction(settings):
    ctx = build_context(settings)
    fn = EmailAssistantTool().create(ctx)
    out = asyncio.run(fn(action="draft"))
    assert out["error"]
    assert out["subject"] == ""


def test_email_assistant_summarize_empty_source(settings):
    ctx = build_context(settings)
    fn = EmailAssistantTool().create(ctx)
    out = asyncio.run(fn(action="summarize"))
    assert out["messages"] == []
    assert "No email content" in out["summary"]
