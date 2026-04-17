"""
Webhook routes for external messaging integrations.

Endpoints:
  POST /webhooks/telegram   — receives Telegram Bot updates
  GET  /webhooks/whatsapp   — Meta webhook verification challenge
  POST /webhooks/whatsapp   — receives WhatsApp Cloud API updates
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Adapters are initialised once at module import (lazy init via settings).
_telegram = TelegramAdapter()
_whatsapp = WhatsAppAdapter()


# ==========================================================================
# HELPERS
# ==========================================================================


async def _process_and_reply_telegram(chat_id: int, user_text: str) -> None:
    """Background task: send user text through AmadeusService, reply via Telegram."""
    try:
        from src.app.services.amadeus_service import AmadeusService

        service = AmadeusService(session_id=str(chat_id), auto_start_orchestrator=False)
        await service.initialize()

        response = await service.handle_command(user_text, source="telegram")
        reply_text = response if isinstance(response, str) else str(response)
        await _telegram.send_message(chat_id, reply_text)
    except Exception:
        logger.exception("telegram_background_processing_failed")
        await _telegram.send_message(chat_id, "⚠️ Sorry, something went wrong. Please try again.")


async def _process_and_reply_whatsapp(phone: str, user_text: str, message_id: str) -> None:
    """Background task: send user text through AmadeusService, reply via WhatsApp."""
    try:
        from src.app.services.amadeus_service import AmadeusService

        service = AmadeusService(session_id=phone, auto_start_orchestrator=False)
        await service.initialize()

        response = await service.handle_command(user_text, source="whatsapp")
        reply_text = response if isinstance(response, str) else str(response)
        await _whatsapp.send_message(phone, reply_text)
        await _whatsapp.mark_as_read(message_id)
    except Exception:
        logger.exception("whatsapp_background_processing_failed")
        await _whatsapp.send_message(phone, "⚠️ Sorry, something went wrong. Please try again.")


# ==========================================================================
# (TELEGRAM WEBHOOK REMOVED - USING LONG POLLING INSTEAD)
# ==========================================================================


# ==========================================================================
# WHATSAPP WEBHOOK
# ==========================================================================


@router.get("/whatsapp", status_code=status.HTTP_200_OK)
async def whatsapp_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Any:
    """Meta webhook verification (GET challenge)."""
    result = _whatsapp.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")
    return int(result)


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """
    Receive WhatsApp Cloud API messages.

    Processing is offloaded to a background task so Meta gets an
    immediate 200 OK.
    """
    payload: dict[str, Any] = await request.json()
    message = WhatsAppAdapter.parse_payload(payload)

    if message is None:
        return {"status": "ignored"}

    logger.info(
        "whatsapp_update_received",
        extra={"from": message.phone_number, "name": message.display_name},
    )

    background_tasks.add_task(
        _process_and_reply_whatsapp,
        message.phone_number,
        message.text,
        message.message_id,
    )
    return {"status": "ok"}
