"""
Outbound Messaging Management Routes for Amadeus AI.

Provides a unified dispatch endpoint that routes outbound messages
to the correct channel adapter (Telegram or Email).

Endpoints:
    POST /api/v1/messaging/send   — send a message on any channel
    GET  /api/v1/messaging/status — check which channels are ready
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.middleware.rbac import RequireAdmin
from src.app.services.messaging_service import MessagingService
from src.container import get_messaging_service
from src.infra.persistence.orm_models import UserORM


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messaging", tags=["Messaging"])


# =============================================================================
# REQUEST / RESPONSE SCHEMAS
# =============================================================================


class SendMessageRequest(BaseModel):
    """Outbound message dispatch request."""

    channel: Literal["telegram", "email"] = Field(
        description="Target channel: 'telegram' or 'email'."
    )
    to: str = Field(
        description=(
            "Recipient identifier — Telegram chat_id (int as string), "
            "or email address."
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
    _admin: UserORM = Depends(RequireAdmin),
    messaging: MessagingService = Depends(get_messaging_service),
) -> SendMessageResponse:
    """
    Dispatch an outbound message to Telegram or Email.

    Admin-only: this sends as the bot / configured mailbox to any recipient.
    """
    try:
        success = await messaging.send_message(
            recipient_id=req.to,
            text=req.message,
            platform=req.channel,
            subject=req.subject
        )

        return SendMessageResponse(
            success=success,
            channel=req.channel,
            detail="sent" if success else "delivery_failed",
        )

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
async def messaging_status(
    messaging: MessagingService = Depends(get_messaging_service),
) -> StatusResponse:
    """
    Returns a real-time readiness check for each messaging channel.
    Requires an authenticated user (enforced at router registration).
    """
    return StatusResponse(
        telegram=messaging.telegram.is_ready if messaging.telegram else False,
        email=messaging.email.is_configured if messaging.email else False,
    )
