"""
Telegram Bot Adapter for Amadeus AI — powered by python-telegram-bot v20+.

Responsibilities:
  - Register a webhook URL with Telegram (called once on deploy).
  - Parse incoming Update payloads using the library's native Update.de_json().
  - Send text replies with optional inline keyboards.
  - Send voice/audio replies.

Why python-telegram-bot v20+?
  - Fully async (asyncio-native) — perfect for FastAPI.
  - Native Update parsing with type safety, no manual dict crawling.
  - Built-in Markdown/HTML parse-mode helpers.
  - InlineKeyboardMarkup support for interactive bot UIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.config import get_settings


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parsed Message Dataclass (preserved for backward compat with existing routes)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TelegramMessage:
    """Parsed incoming Telegram message (text only)."""

    chat_id: int
    text: str
    message_id: int
    from_user_id: int
    from_username: str | None = None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class TelegramAdapter:
    """
    Asynchronous Telegram Bot adapter backed by python-telegram-bot v20+.

    Usage:
        adapter = TelegramAdapter()

        # Register webhook (call once at server startup):
        await adapter.set_webhook("https://your-domain.com/api/v1/messaging/telegram")

        # In your FastAPI route that receives POST payloads from Telegram:
        msg = adapter.parse_update(request_body_dict)
        if msg:
            await adapter.send_message(msg.chat_id, "Hello!")
    """

    def __init__(self, bot_token: str | None = None) -> None:
        settings = get_settings()
        self._token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self._bot: Any = None

        if not self._token:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is not configured — Telegram adapter disabled"
            )
            return

        self._init_bot()

    def _init_bot(self) -> None:
        """Initialize a python-telegram-bot Bot instance."""
        try:
            from telegram import Bot  # type: ignore[import-untyped]
            self._bot = Bot(token=self._token)
            logger.info("python-telegram-bot Bot instance created (async-ready)")
        except ImportError:
            logger.error(
                "python-telegram-bot is not installed. "
                "Run: pip install 'python-telegram-bot[webhooks]>=20.7'"
            )
            self._bot = None

    # -----------------------------------------------------------------------
    # Inbound — parse raw webhook payload
    # -----------------------------------------------------------------------

    def parse_update(self, payload: dict[str, Any]) -> TelegramMessage | None:
        """
        Parse a raw Telegram Update JSON into a TelegramMessage.

        Uses python-telegram-bot's native Update.de_json() for reliable
        deserialization, then falls back to manual parsing if the library
        is unavailable.

        Returns None for non-text updates (stickers, edits, voice, etc.).
        """
        # -- Library path (preferred) ----------------------------------------
        if self._bot is not None:
            try:
                from telegram import Update, Bot  # type: ignore[import-untyped]
                update = Update.de_json(payload, self._bot)
                if update is None or update.message is None or update.message.text is None:
                    return None
                msg = update.message
                return TelegramMessage(
                    chat_id=msg.chat_id,
                    text=msg.text,
                    message_id=msg.message_id,
                    from_user_id=msg.from_user.id if msg.from_user else 0,
                    from_username=msg.from_user.username if msg.from_user else None,
                )
            except Exception as exc:
                logger.warning("Update.de_json failed, falling back to manual parse: %s", exc)

        # -- Fallback: manual dict traversal (no library) --------------------
        message = payload.get("message")
        if not message or "text" not in message:
            return None

        chat = message.get("chat", {})
        from_user = message.get("from", {})
        return TelegramMessage(
            chat_id=chat.get("id", 0),
            text=message["text"],
            message_id=message.get("message_id", 0),
            from_user_id=from_user.get("id", 0),
            from_username=from_user.get("username"),
        )

    # -----------------------------------------------------------------------
    # Outbound — send replies
    # -----------------------------------------------------------------------

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a text message to a Telegram chat.

        Args:
            chat_id: Telegram chat or user ID.
            text: Message body (supports Markdown by default).
            parse_mode: "Markdown", "MarkdownV2", or "HTML".

        Returns:
            True on success, False on failure.
        """
        if self._bot is None:
            logger.error("Cannot send — Telegram bot not initialized")
            return False

        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            logger.info("telegram_message_sent chat_id=%s", chat_id)
            return True
        except Exception as exc:
            logger.error("telegram_send_failed chat_id=%s error=%s", chat_id, exc)
            return False

    async def send_buttons(
        self,
        chat_id: int,
        text: str,
        buttons: list[list[dict[str, str]]],
    ) -> bool:
        """
        Send a text message with an inline keyboard.

        Args:
            chat_id: Telegram chat or user ID.
            text: Message body text.
            buttons: 2D list of button dicts. Each dict must have
                     "text" (display label) and "callback_data" (payload).

                     Example:
                     [
                         [{"text": "✅ Yes", "callback_data": "confirm_yes"},
                          {"text": "❌ No",  "callback_data": "confirm_no"}],
                     ]

        Returns:
            True on success, False on failure.
        """
        if self._bot is None:
            logger.error("Cannot send buttons — Telegram bot not initialized")
            return False

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore[import-untyped]

            keyboard = [
                [
                    InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                    for btn in row
                ]
                for row in buttons
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
            )
            logger.info("telegram_buttons_sent chat_id=%s buttons=%d", chat_id, sum(len(r) for r in buttons))
            return True
        except Exception as exc:
            logger.error("telegram_buttons_send_failed chat_id=%s error=%s", chat_id, exc)
            return False

    async def send_voice(
        self,
        chat_id: int,
        audio_bytes: bytes,
        filename: str = "reply.ogg",
    ) -> bool:
        """
        Send a voice message to a Telegram chat.

        Args:
            chat_id: Telegram chat or user ID.
            audio_bytes: OGG/Opus audio content.
            filename: Filename hint for Telegram (usually .ogg).

        Returns:
            True on success, False on failure.
        """
        if self._bot is None:
            logger.error("Cannot send voice — Telegram bot not initialized")
            return False

        try:
            import io
            await self._bot.send_voice(
                chat_id=chat_id,
                voice=io.BytesIO(audio_bytes),
                filename=filename,
            )
            logger.info("telegram_voice_sent chat_id=%s", chat_id)
            return True
        except Exception as exc:
            logger.error("telegram_voice_send_failed chat_id=%s error=%s", chat_id, exc)
            return False

    # -----------------------------------------------------------------------
    # Webhook management
    # -----------------------------------------------------------------------

    async def set_webhook(
        self,
        webhook_url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
    ) -> bool:
        """
        Register the webhook URL with Telegram.

        Call this ONCE at server startup (or on deploy). Telegram will send
        all updates to this URL as HTTP POST requests.

        Args:
            webhook_url: Public HTTPS URL of your FastAPI endpoint, e.g.
                         https://your-domain.com/api/v1/messaging/telegram
            secret_token: Optional header token Telegram uses to sign requests
                          (X-Telegram-Bot-Api-Secret-Token). Use TELEGRAM_WEBHOOK_SECRET.
            allowed_updates: List of update types to receive. Defaults to all.

        Returns:
            True if Telegram acknowledged the webhook, False otherwise.
        """
        if self._bot is None:
            logger.error("Cannot set webhook — Telegram bot not initialized")
            return False

        try:
            kwargs: dict[str, Any] = {"url": webhook_url}
            if secret_token:
                kwargs["secret_token"] = secret_token
            if allowed_updates:
                kwargs["allowed_updates"] = allowed_updates

            await self._bot.set_webhook(**kwargs)
            logger.info("telegram_webhook_registered url=%s", webhook_url)
            return True
        except Exception as exc:
            logger.error("telegram_webhook_set_failed error=%s", exc)
            return False

    async def delete_webhook(self) -> bool:
        """
        Remove the registered webhook (switches bot to polling mode).

        Useful for local development where you don't have a public HTTPS URL.

        Returns:
            True on success, False on failure.
        """
        if self._bot is None:
            return False

        try:
            await self._bot.delete_webhook(drop_pending_updates=True)
            logger.info("telegram_webhook_deleted (polling mode active)")
            return True
        except Exception as exc:
            logger.error("telegram_webhook_delete_failed error=%s", exc)
            return False

    @property
    def is_ready(self) -> bool:
        """True if the bot token is set and the Bot instance is initialized."""
        return self._bot is not None
