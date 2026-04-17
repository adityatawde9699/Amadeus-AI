"""
Telegram Bot Adapter for Amadeus AI — powered by python-telegram-bot v20+.

Responsibilities:
  - Run a long-polling loop in the background (no webhooks).
  - Parse incoming Updates and pass them to AmadeusService.
  - Send text replies with optional inline keyboards.
  - Send voice/audio replies.

Why python-telegram-bot v20+?
  - Fully async (asyncio-native) — perfect for FastAPI.
  - Native Update parsing with type safety.
  - Built-in Markdown/HTML parse-mode helpers.
  - Runs perfectly behind a home NAT without ngrok via Long Polling.
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

        # Start polling (e.g., in FastAPI lifespan):
        await adapter.start_polling()

        # Stop polling (e.g., in FastAPI shutdown):
        await adapter.stop_polling()
    """

    def __init__(self, bot_token: str | None = None) -> None:
        settings = get_settings()
        self._token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self._application: Any = None
        self._bot: Any = None

        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN is not configured — Telegram adapter disabled")
            return

        self._init_application()

    def _init_application(self) -> None:
        """Initialize a python-telegram-bot Application instance for polling."""
        try:
            from telegram.ext import (
                ApplicationBuilder,
                MessageHandler,
                filters,
            )

            # Using ApplicationBuilder is required for v20+ polling
            assert self._token is not None, "Token must be set at this point"
            self._application = ApplicationBuilder().token(self._token).build()
            self._bot = self._application.bot

            # Register the main message handler
            self._application.add_handler(
                MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message)
            )

            logger.info("python-telegram-bot Application instance created for long polling")
        except ImportError:
            logger.exception(
                "python-telegram-bot is not installed. Run: pip install 'python-telegram-bot>=20.7'"
            )
            self._application = None
            self._bot = None

    # -----------------------------------------------------------------------
    # Manual payload parsing (for webhook / test usage)
    # -----------------------------------------------------------------------

    def parse_update(self, payload: dict) -> TelegramMessage | None:
        """
        Parse a raw Telegram Update dict into a TelegramMessage.

        This provides a library-independent parsing path for webhook
        payloads and unit tests.  The long-polling path uses
        python-telegram-bot's own Update objects instead.

        Args:
            payload: Raw JSON dict from a Telegram webhook POST.

        Returns:
            TelegramMessage if the update contains a text message,
            None otherwise.
        """
        message = payload.get("message")
        if not message:
            return None

        text = message.get("text")
        if not text:
            return None

        chat = message.get("chat", {})
        from_user = message.get("from", {})

        return TelegramMessage(
            chat_id=chat.get("id", 0),
            text=text,
            message_id=message.get("message_id", 0),
            from_user_id=from_user.get("id", 0),
            from_username=from_user.get("username"),
        )

    # -----------------------------------------------------------------------
    # Inbound — Polling loop handlers
    # -----------------------------------------------------------------------

    async def _handle_message(self, update: Any, context: Any) -> None:
        """
        Callback for python-telegram-bot to process incoming text messages.
        Passes the extracted information directly to the AmadeusService.
        """
        if not update.message or not update.message.text:
            return

        msg = update.message
        chat_id = msg.chat_id
        text = msg.text

        logger.info(f"Received telegram message from chat_id={chat_id}")

        try:
            from src.app.services.amadeus_service import AmadeusService

            # Instantiate AmadeusService isolated to this user session (chat_id)
            service = AmadeusService(session_id=str(chat_id), auto_start_orchestrator=False)
            await service.initialize()

            # Handle command
            response = await service.handle_command(text, source="telegram")
            reply_text = response if isinstance(response, str) else str(response)

            # Send the reply back
            await self.send_message(chat_id, reply_text)
        except Exception:
            logger.exception("telegram_polling_processing_failed")
            await self.send_message(
                chat_id, "⚠️ Sorry, something went wrong processing your request."
            )

    async def start_polling(self) -> bool:
        """
        Start the background long-polling loop.
        Call this in the FastAPI lifespan startup event.
        """
        if not self._application:
            return False

        try:
            # Initialize and start the application
            await self._application.initialize()
            await self._application.start()
            # Start fetching updates
            await self._application.updater.start_polling()
            logger.info("Telegram long polling started successfully")
            return True
        except Exception as exc:
            logger.exception(f"Failed to start telegram polling: {exc}")
            return False

    async def stop_polling(self) -> bool:
        """
        Stop the background long-polling loop cleanly.
        Call this in the FastAPI lifespan shutdown event.
        """
        if not self._application:
            return False

        try:
            # Stop the updater and application
            if self._application.updater:
                await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            logger.info("Telegram long polling stopped successfully")
            return True
        except Exception as exc:
            logger.exception(f"Failed to stop telegram polling: {exc}")
            return False

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
            logger.exception("telegram_send_failed chat_id=%s error=%s", chat_id, exc)
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
            from telegram import (
                InlineKeyboardButton,
                InlineKeyboardMarkup,
            )

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
            logger.info(
                "telegram_buttons_sent chat_id=%s buttons=%d", chat_id, sum(len(r) for r in buttons)
            )
            return True
        except Exception as exc:
            logger.exception("telegram_buttons_send_failed chat_id=%s error=%s", chat_id, exc)
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
            logger.exception("telegram_voice_send_failed chat_id=%s error=%s", chat_id, exc)
            return False

    @property
    def is_ready(self) -> bool:
        """True if the bot token is set and the Bot instance is initialized."""
        return self._bot is not None
