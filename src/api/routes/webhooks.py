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


async def _process_and_reply_whatsapp(phone: str, user_text: str, message_id: str) -> None:
    """Background task: send user text through AmadeusService, reply via WhatsApp.

    ARCH-01: Reuses the DI-container singleton AmadeusService.
    """
    try:
        from src.container import global_container

        service = global_container.amadeus_service()
        response = await service.handle_command(
            user_text, source="whatsapp", session_id=phone
        )
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

    SEC-02: Verifies the X-Hub-Signature-256 HMAC header sent by Meta before
    processing any payload. Requests without a valid signature are rejected
    immediately with HTTP 403, preventing forged webhook attacks.

    Processing is offloaded to a background task so Meta gets an immediate 200 OK.
    """
    # ── HMAC verification (SEC-02) ───────────────────────────────────────────
    settings = get_settings()
    app_secret = getattr(settings, "WHATSAPP_APP_SECRET", None)
    if app_secret:
        raw_body = await request.body()
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected_sig = "sha256=" + hmac.new(
            app_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected_sig):
            logger.warning("WhatsApp webhook HMAC verification failed — rejecting request")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature",
            )
        payload: dict[str, Any] = __import__("json").loads(raw_body)
    else:
        # No secret configured — log a warning and proceed (dev mode)
        logger.warning(
            "WHATSAPP_APP_SECRET not set — HMAC verification skipped (SEC-02 unmitigated)"
        )
        payload = await request.json()
    # ────────────────────────────────────────────────────────────────────────
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
