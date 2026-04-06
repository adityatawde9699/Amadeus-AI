"""
Email Adapter for Amadeus AI.

Reading:  imap_tools (synchronous — wrapped via asyncio.to_thread)
Sending:  aiosmtplib (fully asynchronous)

Production notes:
  - For Gmail / Microsoft, use OAuth2 App Passwords or service-account tokens.
  - Raw HTML is stripped via BeautifulSoup before handing to the LLM.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from bs4 import BeautifulSoup
from imap_tools import AND, MailBox

from src.core.config import get_settings


logger = logging.getLogger(__name__)


# =========================================================================
# Data Transfer Objects
# =========================================================================

@dataclass(frozen=True)
class ParsedEmail:
    """Cleaned email ready for LLM consumption."""

    uid: str
    message_id: str  # RFC 822 Message-ID
    subject: str
    sender: str
    date: datetime
    body_plain: str  # stripped text — safe for LLM
    has_attachments: bool = False


# =========================================================================
# HTML → Plain-text Pipeline
# =========================================================================

def _strip_html(html: str, max_chars: int = 4000) -> str:
    """
    Aggressive HTML stripping for LLM consumption.

    Removes tags, scripts, styles, and trims output to avoid
    blowing through the context window.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Kill scripts and styles
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = "\n".join(lines)

    return clean[:max_chars]


# =========================================================================
# Email Adapter
# =========================================================================

class EmailAdapter:
    """
    Asynchronous email adapter using imap_tools (sync, threaded) + aiosmtplib.

    All IMAP calls are offloaded to a thread via ``asyncio.to_thread``
    to prevent blocking the FastAPI event loop.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._imap_server = settings.EMAIL_IMAP_SERVER
        self._smtp_server = settings.EMAIL_SMTP_SERVER
        self._smtp_port = settings.EMAIL_SMTP_PORT
        self._email = settings.EMAIL_ADDRESS
        self._password = settings.EMAIL_APP_PASSWORD

        if not self._email or not self._password:
            logger.warning("Email credentials not configured — EmailAdapter disabled")

    @property
    def is_configured(self) -> bool:
        return bool(self._email and self._password)

    # ------------------------------------------------------------------
    # Read (IMAP via imap_tools — threaded)
    # ------------------------------------------------------------------

    def _fetch_unread_sync(self, limit: int = 10) -> list[ParsedEmail]:
        """Synchronous IMAP fetch — called inside asyncio.to_thread."""
        results: list[ParsedEmail] = []

        assert self._email is not None and self._password is not None
        with MailBox(self._imap_server).login(self._email, self._password) as mailbox:
            for msg in mailbox.fetch(AND(seen=False), limit=limit, reverse=True):
                body = msg.text or _strip_html(msg.html or "")
                results.append(
                    ParsedEmail(
                        uid=str(msg.uid or ""),
                        message_id=msg.headers.get("message-id", [""])[0],
                        subject=msg.subject or "(no subject)",
                        sender=msg.from_ or "unknown",
                        date=msg.date or datetime.now(tz=UTC),
                        body_plain=body[:4000],
                        has_attachments=bool(msg.attachments),
                    )
                )

        return results

    async def fetch_unread(self, limit: int = 10) -> list[ParsedEmail]:
        """Fetch unread emails asynchronously (offloaded to thread)."""
        if not self.is_configured:
            logger.error("EmailAdapter not configured")
            return []

        try:
            return await asyncio.to_thread(self._fetch_unread_sync, limit)
        except Exception:
            logger.exception("imap_fetch_failed")
            return []

    # ------------------------------------------------------------------
    # Send (SMTP via aiosmtplib — fully async)
    # ------------------------------------------------------------------

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
    ) -> bool:
        """Send an email asynchronously."""
        if not self.is_configured:
            logger.error("EmailAdapter not configured")
            return False

        message = MIMEMultipart()
        message["From"] = self._email or ""
        message["To"] = to
        message["Subject"] = subject
        if reply_to_message_id:
            message["In-Reply-To"] = reply_to_message_id
            message["References"] = reply_to_message_id
        message.attach(MIMEText(body, "plain"))

        try:
            assert self._email is not None and self._password is not None
            await aiosmtplib.send(
                message,
                hostname=self._smtp_server,
                port=self._smtp_port,
                username=self._email,
                password=self._password,
                start_tls=True,
            )
            logger.info("email_sent", extra={"to": to, "subject": subject})
            return True
        except Exception:
            logger.exception("smtp_send_failed")
            return False
