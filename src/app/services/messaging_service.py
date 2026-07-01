"""
Messaging Service for Amadeus AI.

Unifies Telegram, Email, and other messaging platforms.
"""

import logging

from src.core.config import get_settings
from src.infra.messaging.email_adapter import EmailAdapter
from src.transports.telegram_transport import TelegramTransport


logger = logging.getLogger(__name__)


class MessagingService:
    """
    Service to handle outbound messages across different platforms.
    """

    def __init__(
        self,
        telegram_transport: TelegramTransport | None = None,
        email_adapter: EmailAdapter | None = None,
    ) -> None:
        self.settings = get_settings()
        self.telegram = telegram_transport
        self.email = email_adapter or EmailAdapter()

    async def send_message(
        self,
        recipient_id: str,
        text: str,
        platform: str = "telegram",
        subject: str | None = None,
    ) -> bool:
        """
        Send a message to a recipient on a specific platform.
        """
        platform = platform.lower()

        if platform == "telegram":
            if not self.telegram:
                logger.error("Telegram transport not initialized")
                return False
            try:
                return await self.telegram.send_message(int(recipient_id), text)
            except ValueError:
                logger.exception("Invalid chat_id for Telegram: %s", recipient_id)
                return False

        if platform == "email":
            if not self.email.is_configured:
                logger.error("Email adapter not configured")
                return False
            return await self.email.send_email(
                to=recipient_id,
                subject=subject or "Message from Amadeus",
                body=text
            )

        logger.error("Unsupported messaging platform: %s", platform)
        return False

    async def broadcast(self, text: str, platforms: list[str] | None = None) -> dict[str, bool]:
        """
        Send a message to all configured master accounts.
        """
        platforms = platforms or ["telegram", "email"]
        results = {}

        if "telegram" in platforms and self.telegram and self.settings.MASTER_TELEGRAM_CHAT_ID:
            chat_ids = [cid.strip() for cid in self.settings.MASTER_TELEGRAM_CHAT_ID.split(",") if cid.strip()]
            for cid in chat_ids:
                results[f"telegram:{cid}"] = await self.send_message(cid, text, platform="telegram")

        if "email" in platforms and self.email.is_configured and self.settings.EMAIL_ADDRESS:
            results[f"email:{self.settings.EMAIL_ADDRESS}"] = await self.send_message(
                self.settings.EMAIL_ADDRESS, text, platform="email", subject="Amadeus Notification"
            )

        return results
