"""Email assistant tool: draft, summarize and triage email."""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.providers.base import ChatMessage
from mcp_tool_suite.registry import ToolCallable
from mcp_tool_suite.services.documents import load_text
from mcp_tool_suite.services.email_analysis import (
    extract_action_items,
    mailbox_summary,
    message_headers,
    parse_mailbox,
)

_DRAFT_SYSTEM = (
    "You are an expert email writer. Write a concise, well-structured email that "
    "matches the requested tone and length. Output the subject on a line starting "
    "with 'Subject:', then a blank line, then the body."
)
_SUMMARY_SYSTEM = (
    "You are an email assistant. Summarize the mailbox: who wrote, what they want, "
    "and any decisions or outstanding threads. Be concise and use short bullets."
)
_ACTIONS_SYSTEM = (
    "You are an email assistant. Given extracted action items, produce a single "
    "consolidated, deduplicated checklist of concrete action items. Be concise."
)


def _summary_prompt(headers: list[dict[str, object]]) -> str:
    blocks = []
    for i, message in enumerate(headers, start=1):
        blocks.append(
            f"[{i}] From: {message.get('from')}\n"
            f"Subject: {message.get('subject')}\n"
            f"Date: {message.get('date')}\n"
            f"{message.get('preview', '')}"
        )
    return "Summarize this mailbox:\n\n" + "\n\n".join(blocks)


def _actions_prompt(items: list[dict[str, object]]) -> str:
    if not items:
        return "No action items were detected in the mailbox."
    lines = [f"- {item.get('text')}" for item in items]
    return "Consolidate these extracted action items into a concise checklist:\n\n" + "\n".join(lines)


def _split_subject(text: str, fallback: str) -> tuple[str, str]:
    lowered = text.lower()
    index = lowered.find("subject:")
    if index != -1:
        after = text[index + len("subject:") :]
        line, _, rest = after.partition("\n")
        subject = line.strip()
        body = rest.strip()
        if subject and body:
            return subject, body
    stripped = text.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if first_line.lower().startswith("[fake"):
        subject = fallback.strip()[:80] or "Draft email"
    else:
        subject = first_line
    return subject[:120], stripped


class EmailAssistantTool:
    name = "email_assistant"
    description = (
        "Draft, summarize or triage email. `action=\"draft\"` writes an email from an "
        "instruction; `action=\"summarize\"` summarizes a mailbox; "
        "`action=\"extract_actions\"` pulls out action items and open questions. The "
        "source may be raw email/mbox text, a local file path or an http(s) URL."
    )

    def create(self, ctx: AppContext) -> ToolCallable:
        async def email_assistant(
            source: str = "",
            action: str = "summarize",
            instruction: str = "",
            recipient: str = "",
            tone: str = "professional",
            max_words: int = 200,
        ) -> dict:
            """Draft, summarize or extract action items from email."""
            action = (action or "summarize").strip().lower()

            if action == "draft":
                return await self._draft(ctx, instruction, recipient, tone, max_words)

            raw = (
                await load_text(source, timeout=ctx.settings.request_timeout)
                if source.strip()
                else ""
            )
            messages = parse_mailbox(raw)
            stats = mailbox_summary(messages)
            headers = message_headers(messages)

            if action == "extract_actions":
                items = extract_action_items(messages)
                summary = await ctx.llm.complete(
                    [
                        ChatMessage("system", _ACTIONS_SYSTEM),
                        ChatMessage("user", _actions_prompt(items)),
                    ]
                )
                return {
                    "action": "extract_actions",
                    "messages": headers,
                    "stats": stats,
                    "action_items": items,
                    "summary": summary,
                }

            if not messages:
                return {
                    "action": "summarize",
                    "messages": [],
                    "stats": stats,
                    "summary": "No email content was provided. Pass `source` as raw "
                    "email/mbox text, a file path or a URL.",
                }

            summary = await ctx.llm.complete(
                [
                    ChatMessage("system", _SUMMARY_SYSTEM),
                    ChatMessage("user", _summary_prompt(headers)),
                ]
            )
            return {
                "action": "summarize",
                "messages": headers,
                "stats": stats,
                "summary": summary,
            }

        return email_assistant

    async def _draft(
        self,
        ctx: AppContext,
        instruction: str,
        recipient: str,
        tone: str,
        max_words: int,
    ) -> dict:
        if not instruction.strip():
            return {
                "action": "draft",
                "recipient": recipient,
                "tone": tone,
                "subject": "",
                "body": "",
                "error": "No `instruction` provided for drafting.",
            }
        user = (
            f"Write an email to {recipient or 'the recipient'} in a "
            f"{tone or 'professional'} tone.\n"
            f"What to say: {instruction}\n"
            f"Keep it under about {max_words} words."
        )
        text = await ctx.llm.complete(
            [ChatMessage("system", _DRAFT_SYSTEM), ChatMessage("user", user)]
        )
        subject, body = _split_subject(text, instruction)
        return {
            "action": "draft",
            "recipient": recipient,
            "tone": tone,
            "subject": subject,
            "body": body,
        }
