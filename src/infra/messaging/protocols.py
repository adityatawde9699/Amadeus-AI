"""
Messaging Adapter Protocol — Phase 12 Architecture Upgrade.

Defines the ``IMessagingAdapter`` Protocol so that all platform adapters
(Telegram, WhatsApp, Slack …) share a common, type-safe interface.

Benefits:
- Unified webhook handler — one ``BaseWebhookHandler`` replaces the
  per-adapter boilerplate in webhooks.py
- Testable in isolation — mock adapters implement the protocol trivially
- Extensible — adding a new platform only requires implementing 4 methods
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import Request


@runtime_checkable
class IMessagingAdapter(Protocol):
    """
    Unified interface every messaging platform adapter must satisfy.

    Phase 12 upgrade: enforces a common contract across Telegram,
    WhatsApp, Slack (and any future adapter) so the webhook layer
    can dispatch calls without knowing the concrete adapter type.
    """

    async def verify_request(self, request: Request) -> bool:
        """
        Return True if the incoming HTTP request is authentic.

        Examples
        --------
        - Telegram: verify ``X-Telegram-Bot-Api-Secret-Token`` header
        - WhatsApp: verify ``X-Hub-Signature-256`` HMAC
        - Slack: verify ``X-Slack-Signature`` HMAC
        """
        ...

    async def parse_message(self, payload: dict) -> "InboundMessage | None":
        """
        Parse the raw webhook payload into a normalised ``InboundMessage``.

        Returns ``None`` when the payload contains no actionable user message
        (e.g. a delivery receipt, status update, or heartbeat event).
        """
        ...

    async def send_reply(self, recipient_id: str, text: str) -> bool:
        """
        Send *text* to *recipient_id* on the platform.

        Returns ``True`` on success, ``False`` on transient failure.
        """
        ...

    async def get_authorized_users(self) -> set[str]:
        """
        Return the set of platform-specific user IDs that are allowed to
        issue commands to Amadeus.

        For Telegram this is the set of allowed ``chat_id`` values parsed
        from ``MASTER_TELEGRAM_CHAT_ID``.  For WhatsApp it comes from
        ``MASTER_WHATSAPP_NUMBER``.
        """
        ...


class InboundMessage:
    """
    Normalised message received from any platform adapter.

    All fields are platform-agnostic so the core AmadeusService layer
    never needs to know where a message came from.
    """

    __slots__ = ("sender_id", "text", "platform", "raw_payload", "message_id")

    def __init__(
        self,
        sender_id: str,
        text: str,
        platform: str,
        raw_payload: dict | None = None,
        message_id: str | None = None,
    ) -> None:
        self.sender_id = sender_id
        self.text = text
        self.platform = platform
        self.raw_payload = raw_payload or {}
        self.message_id = message_id

    def __repr__(self) -> str:
        return (
            f"<InboundMessage platform={self.platform!r} "
            f"sender={self.sender_id!r} text={self.text[:40]!r}>"
        )
