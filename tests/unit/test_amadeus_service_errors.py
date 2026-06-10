"""
Unit tests for AmadeusService error handling.

Validates that:
- Raw Python exceptions are NEVER exposed to users in production mode
- Debug mode shows the exception class name (not full message/traceback)
- A plain "unexpected error" message is returned in production
"""

import sys
import types
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch


if TYPE_CHECKING:
    from src.app.services.amadeus_service import AmadeusService

import pytest


# ---------------------------------------------------------------------------
# Patch heavy optional dependencies at sys.modules level BEFORE any import
# of AmadeusService. These are all top-level imports in amadeus_service.py
# that would fail in a minimal test environment.
# ---------------------------------------------------------------------------

if "google.genai" not in sys.modules:
    _genai: Any = types.ModuleType("google.genai")
    _genai.Client = MagicMock()
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = MagicMock()
    _google: Any = sys.modules.get("google") or types.ModuleType("google")
    _google.genai = _genai
    sys.modules["google"] = _google


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(debug: bool = False) -> "AmadeusService":
    """Create a minimal AmadeusService with all heavy deps mocked out."""
    from src.app.services.amadeus_service import AmadeusService

    with (
        patch("src.app.services.amadeus_service.genai"),
        patch("src.app.services.amadeus_service.QdrantMemoryService") as mock_mem,

        patch("src.app.services.amadeus_service.ToolRegistry"),
        patch("src.app.services.amadeus_service.ToolExecutor"),
        patch("src.app.services.amadeus_service.ArgumentExtractor"),
        patch("src.app.services.amadeus_service.ToolDispatcher"),
        patch("src.app.services.amadeus_service.ResponseComposer"),
        patch("src.app.services.amadeus_service.UnifiedSemanticRouter") as mock_router,
        # AgentOrchestrator is lazily imported inside __init__ from agent_loop
        patch("src.app.services.agent_loop.AgentOrchestrator"),
    ):
        mock_mem.return_value.is_enabled = False
        mock_mem.return_value.store = AsyncMock()
        mock_router.return_value.is_ready = False
        mock_router.return_value.build_index = MagicMock()

        mock_settings = MagicMock()
        mock_settings.GEMINI_API_KEY = None
        mock_settings.DEBUG = debug
        mock_settings.ALLOW_DEBUG_RESPONSES = debug
        mock_settings.ASSISTANT_NAME = "Amadeus"
        mock_settings.ASSISTANT_PERSONALITY = "helpful"
        mock_settings.GEMINI_MODEL = "gemini-flash"
        mock_settings.LOCAL_ONLY_MODE = True
        mock_settings.BASE_DIR = MagicMock()

        svc = AmadeusService(settings=mock_settings, debug_mode=debug)
        svc.client = None  # No Gemini
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
        mock_cm = AsyncMock()
        mock_cm.add.side_effect = RuntimeError("DB connection string: postgres://admin:secret@host/db")
        svc._get_conversation_manager = AsyncMock(return_value=mock_cm)

        context = MagicMock()
        context.session_id = "test"
        context.user_id = "test"
        response = await svc.handle_command("hello", context)

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

        mock_cm = AsyncMock()
        mock_cm.add.side_effect = ValueError("sensitive internal value: TOKEN=abc123")
        svc._get_conversation_manager = AsyncMock(return_value=mock_cm)

        context = MagicMock()
        context.session_id = "test"
        context.user_id = "test"
        response = await svc.handle_command("hello", context)

        # Should include the class name for quick debugging
        assert "ValueError" in response
        # But must NOT include the sensitive message body
        assert "TOKEN=abc123" not in response
        assert "sensitive internal value" not in response

    @pytest.mark.asyncio
    async def test_empty_input_returns_prompt_not_error(self):
        """Empty / whitespace input returns a prompt, not an exception."""
        svc = _make_service(debug=False)
        context = MagicMock()
        response = await svc.handle_command("   ", context)
        assert response  # Non-empty
        assert "error" not in response.lower()

    @pytest.mark.asyncio
    async def test_response_returned_on_success(self):
        """A successful command returns the expected response (no error)."""
        svc = _make_service(debug=False)

        mock_cm = AsyncMock()
        svc._get_conversation_manager = AsyncMock(return_value=mock_cm)
        svc.memory_service.store = AsyncMock()
        svc.memory_service.retrieve = AsyncMock(return_value=[])
        svc.memory_service.format_for_prompt = MagicMock(return_value="")
        svc._process_command_internal = AsyncMock(return_value=("Hello!", None))
        svc._is_multi_step_query = MagicMock(return_value=False)

        context = MagicMock()
        context.session_id = "test"
        context.user_id = "test"
        response = await svc.handle_command("hi there", context)
        assert response == "Hello!"
