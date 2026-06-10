"""
Email tools for Amadeus AI LLM tool registry.

Provides LLM-callable tools: read_unread_emails, send_email.
All tools use the EmailAdapter for I/O.
"""

import logging
from typing import Any

from src.infra.messaging.email_adapter import EmailAdapter
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

_adapter = EmailAdapter()


def get_email_tools() -> list[Tool]:
    """
    Build email tools for the LLM tool registry.

    Returns a list of tool definitions compatible with the ToolRegistry.
    """

    @tool(
        name="read_unread_emails",
        description="Reads unread emails from the configured Gmail inbox via IMAP. Returns sender, subject, date, and a 200-char body preview for each email. Trigger: 'check my email', 'unread emails', 'any new emails', 'read inbox'",
        category=ToolCategory.COMMUNICATION,
        parameters={
            "limit": {"type": "integer", "description": "Max emails to fetch", "default": 5}
        },
    )
    async def read_unread_emails(limit: int = 5, **kwargs: Any) -> str:
        """Read unread emails from the configured inbox. Returns a summary of each email."""
        if not _adapter.is_configured:
            return "⚠️ Email is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env."

        emails = await _adapter.fetch_unread(limit=limit)
        if not emails:
            return "📭 No unread emails found."

        lines = [f"📬 **{len(emails)} unread email(s):**\n"]
        for i, e in enumerate(emails, 1):
            lines.append(
                f"{i}. **From:** {e.sender}\n"
                f"   **Subject:** {e.subject}\n"
                f"   **Date:** {e.date.strftime('%Y-%m-%d %H:%M')}\n"
                f"   **Preview:** {e.body_plain[:200]}...\n"
            )
        return "\n".join(lines)

    @tool(
        name="send_email",
        description="Sends an email via SMTP through the configured Gmail account. Requires recipient address, subject line, and body text. Trigger: 'send email to X', 'email John about Y', 'compose email'",
        category=ToolCategory.COMMUNICATION,
        parameters={
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text"},
        },
        requires_confirmation=True,
    )
    async def send_email(to: str, subject: str, body: str, **kwargs: Any) -> str:
        """Send an email to the specified recipient."""
        if not _adapter.is_configured:
            return "⚠️ Email is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env."

        success = await _adapter.send_email(to=to, subject=subject, body=body)
        if success:
            return f"✅ Email sent to {to} with subject '{subject}'."
        return "❌ Failed to send email. Check logs for details."

    return [
        read_unread_emails._tool_metadata,  # type: ignore[attr-defined]
        send_email._tool_metadata,  # type: ignore[attr-defined]
    ]
