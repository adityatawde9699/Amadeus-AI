"""
WhatsApp Cloud API Adapter for Amadeus AI.

Handles incoming webhook payloads from the Meta Cloud API and
sends responses back using httpx.

Requires a Meta Business App with WhatsApp product configured.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.config import get_settings


logger = logging.getLogger(__name__)

META_GRAPH_API = "https://graph.facebook.com/v21.0"


@dataclass(frozen=True)
class WhatsAppMessage:
    """Parsed incoming WhatsApp message."""

    phone_number: str  # sender's phone (e.g. "919876543210")
    text: str
    message_id: str  # wamid
    display_name: str | None = None


class WhatsAppAdapter:
    """
    Asynchronous adapter for the Meta WhatsApp Cloud API.

    Responsibilities:
      - Verify webhook challenge (hub.verify_token).
      - Parse incoming message payloads.
      - Send text replies.
    """

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        verify_token: str | None = None,
    ) -> None:
        settings = get_settings()
        self._access_token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        self._phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self._verify_token = verify_token or settings.WHATSAPP_VERIFY_TOKEN

        if not self._access_token:
            logger.warning("WHATSAPP_ACCESS_TOKEN not configured — WhatsApp adapter disabled")

    # ------------------------------------------------------------------
    # Webhook Verification (GET challenge from Meta)
    # ------------------------------------------------------------------

    def verify_webhook(
        self, mode: str | None, token: str | None, challenge: str | None
    ) -> str | None:
        """
        Handle Meta's webhook verification.

        Returns the challenge string if verification passes, else None.
        """
        if mode == "subscribe" and token == self._verify_token:
            logger.info("whatsapp_webhook_verified")
            return challenge
        logger.warning("whatsapp_webhook_verification_failed")
        return None

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    @staticmethod
    def parse_payload(payload: dict[str, Any]) -> WhatsAppMessage | None:
        """
        Extract a text message from a Meta webhook payload.

        Returns None for non-text message types (images, status updates, etc.).
        """
        try:
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])

            if not messages:
                return None

            msg = messages[0]
            if msg.get("type") != "text":
                return None

            # Extract contact display name
            contacts = value.get("contacts", [{}])
            display_name = contacts[0].get("profile", {}).get("name") if contacts else None

            return WhatsAppMessage(
                phone_number=msg.get("from", ""),
                text=msg["text"]["body"],
                message_id=msg.get("id", ""),
                display_name=display_name,
            )
        except (KeyError, IndexError):
            logger.exception("whatsapp_payload_parse_error")
            return None

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send_message(self, to_phone: str, text: str) -> bool:
        """Send a text message via the WhatsApp Cloud API."""
        if not self._access_token or not self._phone_number_id:
            logger.error("Cannot send — WhatsApp credentials not configured")
            return False

        url = f"{META_GRAPH_API}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                logger.info("whatsapp_message_sent", extra={"to": to_phone})
                return True
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "whatsapp_send_failed",
                extra={"status": exc.response.status_code, "body": exc.response.text},
            )
            return False

    async def mark_as_read(self, message_id: str) -> None:
        """Mark a received message as read (blue ticks)."""
        if not self._access_token or not self._phone_number_id:
            return

        url = f"{META_GRAPH_API}/{self._phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError:
            pass  # non-critical

    async def send_interactive_buttons(
        self,
        to_phone: str,
        body_text: str,
        buttons: list[dict[str, str]],
        header_text: str | None = None,
        footer_text: str | None = None,
    ) -> bool:
        """
        Send an interactive button message via the Meta WhatsApp Cloud API.

        Enables rich, quick-reply style interactions — the user taps a button
        instead of typing a response.

        Args:
            to_phone: Recipient's phone number (e.g. "919876543210").
            body_text: The main message body shown above the buttons.
            buttons: List of button dicts. Each must have:
                     - "id"    : Unique button identifier (max 256 chars, sent back as reply payload).
                     - "title" : Display label shown to the user (max 20 chars).
                     Maximum 3 buttons allowed by Meta's API.
            header_text: Optional header text shown above the body (max 60 chars).
            footer_text: Optional footer text shown below the buttons (max 60 chars).

        Returns:
            True on success, False on failure.

        Example:
            await adapter.send_interactive_buttons(
                to_phone="919876543210",
                body_text="Would you like a summary of today's news?",
                buttons=[
                    {"id": "news_yes", "title": "✅ Yes please"},
                    {"id": "news_no",  "title": "❌ Not now"},
                ],
            )
        """
        if not self._access_token or not self._phone_number_id:
            logger.error("Cannot send interactive buttons — WhatsApp credentials not configured")
            return False

        if not buttons:
            logger.error("send_interactive_buttons called with empty buttons list")
            return False

        if len(buttons) > 3:
            logger.warning("Meta API allows max 3 buttons; truncating from %d to 3", len(buttons))
            buttons = buttons[:3]

        # Build Meta Cloud API interactive payload
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn["id"],
                            "title": btn["title"][:20],  # Meta enforces 20-char max
                        },
                    }
                    for btn in buttons
                ]
            },
        }

        if header_text:
            interactive["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}

        url = f"{META_GRAPH_API}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": interactive,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                logger.info(
                    "whatsapp_interactive_buttons_sent to=%s buttons=%d",
                    to_phone,
                    len(buttons),
                )
                return True
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "whatsapp_interactive_buttons_failed status=%s body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return False

    async def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        language_code: str = "en_US",
        components: list[dict[str, Any]] | None = None,
    ) -> bool:
        """
        Send a pre-approved WhatsApp message template.

        Template messages are required for initiating conversations (outside
        the 24-hour customer service window). Templates must be approved by
        Meta before use.

        Args:
            to_phone: Recipient's phone number (e.g. "919876543210").
            template_name: The exact name of the approved template in the
                           Meta Business Manager.
            language_code: BCP-47 language code (default: "en_US").
            components: Optional list of template component overrides
                        (for variable substitution, headers, buttons, etc.).

        Returns:
            True on success, False on failure.

        Example:
            await adapter.send_template_message(
                to_phone="919876543210",
                template_name="hello_world",
                language_code="en_US",
            )
        """
        if not self._access_token or not self._phone_number_id:
            logger.error("Cannot send template — WhatsApp credentials not configured")
            return False

        url = f"{META_GRAPH_API}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        template_payload: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template_payload["components"] = components

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": template_payload,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                logger.info("whatsapp_template_sent to=%s template=%s", to_phone, template_name)
                return True
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "whatsapp_template_failed status=%s body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
