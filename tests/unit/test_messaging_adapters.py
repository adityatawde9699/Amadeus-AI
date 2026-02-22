"""
Unit tests for the messaging adapters.

Tests cover:
  - TelegramAdapter.parse_update()       (manual dict + library path)
  - WhatsAppAdapter.verify_webhook()
  - WhatsAppAdapter.parse_payload()
  - WhatsAppAdapter.send_interactive_buttons() (mocked httpx)
  - WhatsAppAdapter.send_template_message()    (mocked httpx)

All network calls are mocked via unittest.mock and httpx.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_telegram_payload(
    chat_id: int = 12345,
    text: str = "Hello bot",
    message_id: int = 1,
    user_id: int = 999,
    username: str | None = "testuser",
) -> dict:
    """Build a minimal Telegram Update payload dict."""
    return {
        "update_id": 100,
        "message": {
            "message_id": message_id,
            "from": {"id": user_id, "username": username, "is_bot": False},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _make_whatsapp_payload(
    phone: str = "919876543210",
    text: str = "Hello bot",
    wamid: str = "wamid.123",
    display_name: str = "Test User",
) -> dict:
    """Build a minimal Meta Cloud API webhook payload."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": display_name}}],
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": phone,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


# ===========================================================================
# Telegram Adapter Tests
# ===========================================================================

class TestTelegramAdapterParseUpdate:
    """Test parse_update() without a live Bot instance."""

    def _adapter_without_bot(self) -> "TelegramAdapter":
        """Create adapter that skips Bot initialization."""
        from src.infra.messaging.telegram_adapter import TelegramAdapter
        with patch("src.infra.messaging.telegram_adapter.get_settings") as mock_settings:
            mock_settings.return_value.TELEGRAM_BOT_TOKEN = None
            adapter = TelegramAdapter.__new__(TelegramAdapter)
            adapter._token = None
            adapter._bot = None
        return adapter

    def test_parse_text_message_manual_path(self) -> None:
        """parse_update() should return a TelegramMessage for a text update (no lib)."""
        from src.infra.messaging.telegram_adapter import TelegramAdapter, TelegramMessage
        adapter = self._adapter_without_bot()
        payload = _make_telegram_payload()
        result = adapter.parse_update(payload)

        assert result is not None
        assert isinstance(result, TelegramMessage)
        assert result.chat_id == 12345
        assert result.text == "Hello bot"
        assert result.from_user_id == 999
        assert result.from_username == "testuser"

    def test_parse_non_text_returns_none(self) -> None:
        """parse_update() should return None for non-text updates."""
        from src.infra.messaging.telegram_adapter import TelegramAdapter
        adapter = self._adapter_without_bot()
        payload = {"update_id": 101, "message": {"chat": {"id": 1}, "sticker": {}}}
        assert adapter.parse_update(payload) is None

    def test_parse_empty_payload_returns_none(self) -> None:
        """parse_update() should return None for an empty dict."""
        from src.infra.messaging.telegram_adapter import TelegramAdapter
        adapter = self._adapter_without_bot()
        assert adapter.parse_update({}) is None

    def test_is_ready_false_when_no_token(self) -> None:
        """is_ready should be False when bot token is missing."""
        from src.infra.messaging.telegram_adapter import TelegramAdapter
        adapter = self._adapter_without_bot()
        assert adapter.is_ready is False


# ===========================================================================
# WhatsApp Adapter Tests
# ===========================================================================

class TestWhatsAppAdapterParsing:
    """Test parsing and webhook verification logic."""

    def _adapter(self) -> "WhatsAppAdapter":
        from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter
        with patch("src.infra.messaging.whatsapp_adapter.get_settings") as mock_settings:
            mock_settings.return_value.WHATSAPP_ACCESS_TOKEN = "fake-token"
            mock_settings.return_value.WHATSAPP_PHONE_NUMBER_ID = "1234567890"
            mock_settings.return_value.WHATSAPP_VERIFY_TOKEN = "my-verify-token"
            adapter = WhatsAppAdapter(
                access_token="fake-token",
                phone_number_id="1234567890",
                verify_token="my-verify-token",
            )
        return adapter

    def test_verify_webhook_succeeds_with_correct_token(self) -> None:
        adapter = self._adapter()
        result = adapter.verify_webhook("subscribe", "my-verify-token", "challenge-xyz")
        assert result == "challenge-xyz"

    def test_verify_webhook_fails_with_wrong_token(self) -> None:
        adapter = self._adapter()
        result = adapter.verify_webhook("subscribe", "wrong-token", "challenge-xyz")
        assert result is None

    def test_parse_payload_text_message(self) -> None:
        from src.infra.messaging.whatsapp_adapter import WhatsAppMessage
        adapter = self._adapter()
        payload = _make_whatsapp_payload(phone="919876543210", text="Hi there")
        msg = adapter.parse_payload(payload)

        assert msg is not None
        assert isinstance(msg, WhatsAppMessage)
        assert msg.phone_number == "919876543210"
        assert msg.text == "Hi there"
        assert msg.display_name == "Test User"

    def test_parse_payload_non_text_returns_none(self) -> None:
        adapter = self._adapter()
        payload = _make_whatsapp_payload()
        # Force non-text message type
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "image"
        assert adapter.parse_payload(payload) is None

    def test_parse_empty_payload_returns_none(self) -> None:
        adapter = self._adapter()
        assert adapter.parse_payload({}) is None


class TestWhatsAppAdapterSend:
    """Test send methods with mocked httpx."""

    def _adapter(self) -> "WhatsAppAdapter":
        from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter
        return WhatsAppAdapter(
            access_token="fake-token",
            phone_number_id="1234567890",
            verify_token="my-verify-token",
        )

    @pytest.mark.asyncio
    async def test_send_interactive_buttons_success(self) -> None:
        """send_interactive_buttons() should POST correct payload and return True."""
        adapter = self._adapter()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await adapter.send_interactive_buttons(
                to_phone="919876543210",
                body_text="Choose an option:",
                buttons=[
                    {"id": "opt_a", "title": "Option A"},
                    {"id": "opt_b", "title": "Option B"},
                ],
            )

        assert result is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        posted_json = call_args.kwargs["json"]
        assert posted_json["type"] == "interactive"
        assert posted_json["interactive"]["type"] == "button"
        assert len(posted_json["interactive"]["action"]["buttons"]) == 2

    @pytest.mark.asyncio
    async def test_send_interactive_buttons_truncates_to_3(self) -> None:
        """send_interactive_buttons() must truncate buttons list to max 3."""
        adapter = self._adapter()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await adapter.send_interactive_buttons(
                to_phone="919876543210",
                body_text="Too many buttons:",
                buttons=[
                    {"id": f"opt_{i}", "title": f"Option {i}"}
                    for i in range(5)         # send 5, should be capped at 3
                ],
            )

        call_args = mock_client.post.call_args
        posted_json = call_args.kwargs["json"]
        assert len(posted_json["interactive"]["action"]["buttons"]) == 3

    @pytest.mark.asyncio
    async def test_send_interactive_buttons_returns_false_when_unconfigured(self) -> None:
        """send_interactive_buttons() returns False when credentials are missing."""
        from src.infra.messaging.whatsapp_adapter import WhatsAppAdapter
        adapter = WhatsAppAdapter(access_token=None, phone_number_id=None, verify_token=None)
        result = await adapter.send_interactive_buttons(
            to_phone="919876543210",
            body_text="hi",
            buttons=[{"id": "x", "title": "X"}],
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_template_message_success(self) -> None:
        """send_template_message() should POST the correct template payload."""
        adapter = self._adapter()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await adapter.send_template_message(
                to_phone="919876543210",
                template_name="hello_world",
                language_code="en_US",
            )

        assert result is True
        call_args = mock_client.post.call_args
        posted_json = call_args.kwargs["json"]
        assert posted_json["type"] == "template"
        assert posted_json["template"]["name"] == "hello_world"
        assert posted_json["template"]["language"]["code"] == "en_US"
