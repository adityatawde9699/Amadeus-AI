"""
Webhook routes for external messaging integrations.

Endpoints:
  POST /webhooks/telegram   — receives Telegram Bot updates
  GET  /webhooks/whatsapp   — Meta webhook verification challenge
  POST /webhooks/whatsapp   — receives WhatsApp Cloud API updates
"""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from src.core.config import get_settings
from src.transports.telegram_transport import TelegramTransport


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Adapters are initialised once at module import (lazy init via settings).
settings = get_settings()

_telegram = TelegramTransport(runtime=None)


# ==========================================================================
# HELPERS
# ==========================================================================


async def _process_and_reply_telegram(chat_id: int, user_text: str) -> None:
    """Background task: send user text through AmadeusService, reply via Telegram.

    ARCH-01: Reuses the DI-container singleton AmadeusService rather than
    constructing a new instance (and Qdrant client) per message.
    """
    try:
        from src.container import global_container

        service = global_container.amadeus_service()
        response = await service.handle_command(
            user_text, source="telegram", session_id=str(chat_id)
        )
        reply_text = response if isinstance(response, str) else str(response)
        await _telegram.send_message(chat_id, reply_text)
    except Exception:
        logger.exception("telegram_background_processing_failed")
        await _telegram.send_message(chat_id, "⚠️ Sorry, something went wrong. Please try again.")



