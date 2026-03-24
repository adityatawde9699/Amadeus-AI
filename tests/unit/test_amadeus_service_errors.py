"""
Unit tests for AmadeusService error handling.

Validates that:
- Raw Python exceptions are NEVER exposed to users in production mode
- Debug mode shows the exception class name (not full message/traceback)
- A plain "unexpected error" message is returned in production
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch heavy optional dependencies at sys.modules level BEFORE any import
# of AmadeusService. These are all top-level imports in amadeus_service.py
# that would fail in a minimal test environment.
# ---------------------------------------------------------------------------

for _mod in ("joblib", "numpy", "numpy.core"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google.genai" not in sys.modules:
    _genai = types.ModuleType("google.genai")
    _genai.Client = MagicMock()
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = MagicMock()
    sys.modules["google"] = sys.modules.get("google") or types.ModuleType("google")
    sys.modules["google"].genai = _genai


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(debug: bool = False) -> "AmadeusService":  # noqa: F821
    """Create a minimal AmadeusService with all heavy deps mocked out."""
    from src.app.services.amadeus_service import AmadeusService

    with (
        patch("src.app.services.amadeus_service.genai"),
        patch("src.app.services.amadeus_service.joblib"),
        patch("src.app.services.amadeus_service.QdrantMemoryService") as mock_mem,
        patch("src.app.services.amadeus_service.ToolRegistry"),
        patch("src.app.services.amadeus_service.ToolExecutor"),
        # AgentOrchestrator is lazily imported *inside* __init__ from agent_loop;
        # patch it at the source module so the local `from ... import` picks it up.
        patch("src.app.services.agent_loop.AgentOrchestrator"),
        patch("src.infra.messaging.telegram_adapter.TelegramAdapter"),
        patch("src.infra.messaging.whatsapp_adapter.WhatsAppAdapter"),
    ):
        mock_mem.return_value.is_enabled = False
        mock_mem.return_value.memory_count = 0

        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = None
        mock_settings.DEBUG = debug
        mock_settings.ALLOW_DEBUG_RESPONSES = debug
        mock_settings.ASSISTANT_NAME = "Amadeus"
        mock_settings.ASSISTANT_PERSONALITY = "helpful"
        mock_settings.GEMINI_MODEL = "gemini-flash"

        svc = AmadeusService(settings=mock_settings, debug_mode=debug)
        svc.model = None  # No Gemini
    return svc



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHandleCommandErrorHandling:
    @pytest.mark.asyncio
    async def test_production_mode_hides_error_details(self):
        """
        In production mode (DEBUG=False, debug_mode=False), a crash in
        handle_command must NOT expose the raw exception message to the user.
        """
        svc = _make_service(debug=False)

        # Force an exception deep inside conversation manager
        svc.conversation_manager.add = AsyncMock(
            side_effect=RuntimeError("DB connection string: postgres://admin:secret@host/db")
        )

        response = await svc.handle_command("hello")

        # The response must not contain any hint of the real error
        assert "postgres" not in response
        assert "secret" not in response
        assert "RuntimeError" not in response
        assert "unexpected error" in response.lower()

    @pytest.mark.asyncio
    async def test_debug_mode_shows_error_class_not_message(self):
        """
        In debug mode, the error class name is surfaced (helpful for devs)
        but the full error message / traceback is NOT returned.
        """
        svc = _make_service(debug=True)
        svc.debug_mode = True

        svc.conversation_manager.add = AsyncMock(
            side_effect=ValueError("sensitive internal value: TOKEN=abc123")
        )

        response = await svc.handle_command("hello")

        # Should include the class name for quick debugging
        assert "ValueError" in response
        # But must NOT include the sensitive message body
        assert "TOKEN=abc123" not in response
        assert "sensitive internal value" not in response

    @pytest.mark.asyncio
    async def test_empty_input_returns_prompt_not_error(self):
        """Empty / whitespace input returns a prompt, not an exception."""
        svc = _make_service(debug=False)
        response = await svc.handle_command("   ")
        assert response  # Non-empty
        assert "error" not in response.lower()

    @pytest.mark.asyncio
    async def test_response_returned_on_success(self):
        """A successful command returns the expected response (no error)."""
        svc = _make_service(debug=False)

        # Mock the conversation_manager and internal processing to succeed
        svc.conversation_manager.add = AsyncMock()
        svc.memory_service.store = AsyncMock()
        svc.memory_service.retrieve = AsyncMock(return_value=[])
        svc.memory_service.format_for_prompt = MagicMock(return_value="")
        svc._process_command_internal = AsyncMock(return_value=("Hello!", None))
        svc._is_multi_step_query = MagicMock(return_value=False)

        response = await svc.handle_command("hi there")
        assert response == "Hello!"
