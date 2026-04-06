"""
Email tools for Amadeus AI LLM tool registry.

Provides LLM-callable tools: read_unread_emails, draft_email_reply, send_email.
All tools use the EmailAdapter for I/O.
"""

import logging

from src.infra.messaging.email_adapter import EmailAdapter


logger = logging.getLogger(__name__)

_adapter = EmailAdapter()


def build_email_tools() -> list[dict]:
    """
    Build email tools for the LLM tool registry.

    Returns a list of tool definitions compatible with the ToolRegistry.
    """

    async def read_unread_emails(limit: int = 5) -> str:
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

    async def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to the specified recipient."""
        if not _adapter.is_configured:
            return "⚠️ Email is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env."

        success = await _adapter.send_email(to=to, subject=subject, body=body)
        if success:
            return f"✅ Email sent to {to} with subject '{subject}'."
        return "❌ Failed to send email. Check logs for details."

    return [
        {
            "name": "read_unread_emails",
            "description": "Read unread emails from the inbox. Returns sender, subject, date, and preview.",
            "function": read_unread_emails,
            "parameters": {
                "limit": {"type": "integer", "description": "Max emails to fetch", "default": 5}
            },
        },
        {
            "name": "send_email",
            "description": "Send an email. Requires to, subject, and body.",
            "function": send_email,
            "parameters": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
            },
        },
    ]
