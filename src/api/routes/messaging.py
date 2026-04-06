"""
Outbound Messaging Management Routes for Amadeus AI.

Provides a unified dispatch endpoint that routes outbound messages
to the correct channel adapter (Telegram, WhatsApp, or Email).

Endpoints:
    POST /api/v1/messaging/send   — send a message on any channel
    GET  /api/v1/messaging/status — check which channels are ready
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.middleware.authentication import verify_jwt_token
from src.infra.messaging.email_adapter import EmailAdapter
from src.infra.messaging.telegram_adapter import TelegramAdapter
from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messaging", tags=["Messaging"])

# Singletons — lazy-initialized from settings
_telegram = TelegramAdapter()
_whatsapp = WhatsAppAdapter()
_email = EmailAdapter()


# =============================================================================
# REQUEST / RESPONSE SCHEMAS
# =============================================================================

class SendMessageRequest(BaseModel):
    """Outbound message dispatch request."""

    channel: Literal["telegram", "whatsapp", "email"] = Field(
        description="Target channel: 'telegram', 'whatsapp', or 'email'."
    )
    to: str = Field(
        description=(
            "Recipient identifier — Telegram chat_id (int as string), "
            "WhatsApp phone number (e.g. '919876543210'), or email address."
        )
    )
    message: str = Field(description="Message body to send.")

    # Email-only extras
    subject: str | None = Field(default=None, description="Email subject (email channel only).")


class SendMessageResponse(BaseModel):
    success: bool
    channel: str
    detail: str


class StatusResponse(BaseModel):
    telegram: bool
    whatsapp: bool
    email: bool


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/send",
    response_model=SendMessageResponse,
    summary="Send outbound message on any channel",
)
async def send_message(
    req: SendMessageRequest,
    _token: dict = Depends(verify_jwt_token),
) -> SendMessageResponse:
    """
    Dispatch an outbound message to Telegram, WhatsApp, or Email.

    Requires a valid JWT bearer token.  In production, restrict this
    endpoint to admin-role tokens via the RequireAdmin dependency.
    """
    try:
        if req.channel == "telegram":
            if not _telegram.is_ready:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Telegram adapter is not configured (TELEGRAM_BOT_TOKEN missing)",
                )
            success = await _telegram.send_message(int(req.to), req.message)

        elif req.channel == "whatsapp":
            success = await _whatsapp.send_message(req.to, req.message)

        elif req.channel == "email":
            if not _email.is_configured:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Email adapter is not configured",
                )
            success = await _email.send_email(
                to=req.to,
                subject=req.subject or "Message from Amadeus",
                body=req.message,
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown channel: {req.channel}",
            )

        return SendMessageResponse(
            success=success,
            channel=req.channel,
            detail="sent" if success else "delivery_failed",
        )

    except HTTPException:
        raise
    except ValueError as e:
        # e.g. int("not-a-number") for Telegram chat_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid recipient for {req.channel} channel: {e}",
        ) from e
    except Exception as e:
        logger.exception("messaging_send_error channel=%s error=%s", req.channel, type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message",
        ) from e


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Check which messaging channels are configured and ready",
)
async def messaging_status() -> StatusResponse:
    """
    Returns a real-time readiness check for each messaging channel.
    Does NOT require authentication — useful for health dashboards.
    """
    return StatusResponse(
        telegram=_telegram.is_ready,
        whatsapp=bool(_whatsapp._access_token),  # noqa: SLF001
        email=_email.is_configured,
    )
