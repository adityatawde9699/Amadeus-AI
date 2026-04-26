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


from src.infra.tools.confirmation import ConfirmationCallback
import asyncio

# ---------------------------------------------------------------------------
# Confirmation Callback
# ---------------------------------------------------------------------------

class TelegramConfirmationCallback(ConfirmationCallback):
    """Hits the user up on Telegram for confirmation using inline buttons."""

    def __init__(self, adapter: "TelegramAdapter", chat_id: int):
        self.adapter = adapter
        self.chat_id = chat_id

    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_id: str,
        preview: str = "",
    ) -> bool:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.adapter._pending_confirmations[request_id] = future

        text = (
            f"⚠️ *Confirmation Required*\n\n"
            f"Tool: `{tool_name}`\n"
            f"Preview: {preview}\n"
            f"Args: `{args}`"
        )
        buttons = [
            [
                {"text": "✅ Approve", "callback_data": f"confirm_yes:{request_id}"},
                {"text": "❌ Deny", "callback_data": f"confirm_no:{request_id}"},
            ]
        ]
        
        success = await self.adapter.send_buttons(self.chat_id, text, buttons)
        if not success:
            self.adapter._pending_confirmations.pop(request_id, None)
            return False

        try:
            return await asyncio.wait_for(future, timeout=60)
        except asyncio.TimeoutError:
            return False
        finally:
            self.adapter._pending_confirmations.pop(request_id, None)


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
        self._pending_confirmations: dict[str, asyncio.Future[bool]] = {}

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
                CallbackQueryHandler,
                filters,
            )

            # Using ApplicationBuilder is required for v20+ polling
            if self._token is None:
                raise ValueError("Token must be set at this point")
            self._application = ApplicationBuilder().token(self._token).build()
            self._bot = self._application.bot

            # Register the main message handler
            self._application.add_handler(
                MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message)
            )
            # Register callback query handler for inline button confirmations
            self._application.add_handler(
                CallbackQueryHandler(self._handle_callback_query)
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
        
        import asyncio
        asyncio.create_task(self._process_and_reply_background(chat_id, text))

    async def _process_and_reply_background(self, chat_id: int, text: str) -> None:
        """Runs the AmadeusService inside a background task to unblock the Telegram event loop."""
        try:
            from src.app.services.amadeus_service import AmadeusService
            from src.container import global_container

            # Get dependencies from container to ensure the tool registry is populated
            registry = global_container.tool_registry()
            cache = global_container.cache_service()
            repo = global_container.conversation_repo()
            llm_router = global_container.llm_router()

            # Instantiate AmadeusService isolated to this user session (chat_id)
            service = AmadeusService(
                session_id=str(chat_id),
                auto_start_orchestrator=False,
                tool_registry=registry,
                cache_service=cache,
                conversation_repo=repo,
                llm_router=llm_router,
            )
            
            # Inject Telegram-specific confirmation handler
            service.tool_executor.confirmation_callback = TelegramConfirmationCallback(self, chat_id)
            
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

    async def _handle_callback_query(self, update: Any, context: Any) -> None:
        """Handle inline button clicks for confirmations."""
        query = update.callback_query
        await query.answer()

        data = query.data
        if data and (data.startswith("confirm_yes:") or data.startswith("confirm_no:")):
            approved = data.startswith("confirm_yes:")
            request_id = data.split(":", 1)[1]
            
            future = self._pending_confirmations.get(request_id)
            if future and not future.done():
                future.set_result(approved)
                status = "✅ Approved" if approved else "❌ Denied"
                try:
                    # Edit the message to replace buttons with the resulting status
                    old_text = query.message.text if query.message else "Confirmation Required"
                    await query.edit_message_text(f"{old_text}\n\n*Status*: {status}", parse_mode="Markdown")
                except Exception as e:
                    logger.debug(f"Failed to edit message text: {e}")

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
