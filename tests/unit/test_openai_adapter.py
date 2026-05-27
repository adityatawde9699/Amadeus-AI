"""
Unit tests for the OpenAI LLM adapter.

Tests cover:
- Missing API key raises MissingAPIKeyError
- Successful response returns a string
- HTTP 429 error maps to LLMRateLimitError
- Connection errors map to LLMConnectionError
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Stub heavy imports so tests run without installing them
for _mod in (
    "joblib",
    "google.generativeai",
    "google.generativeai",
    "openai",
    "groq",
    "qdrant_client",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.OPENAI_API_KEY = "sk-test-key"
    s.OPENAI_MODEL = "gpt-4o-mini"
    s.ASSISTANT_NAME = "Amadeus"
    s.ASSISTANT_PERSONALITY = "helpful"
    s.DEFAULT_LOCATION = "Earth"
    s.TIMEZONE = "UTC"
    return s


# =============================================================================
# Missing API key
# =============================================================================


class TestOpenAIAdapterMissingKey:
    def test_missing_key_raises_on_configure(self, mock_settings):
        mock_settings.OPENAI_API_KEY = None
        with patch("src.infra.llm.openai_adapter.get_settings", return_value=mock_settings):
            from src.core.exceptions import MissingAPIKeyError
            from src.infra.llm.openai_adapter import OpenAIAdapter

            adapter = OpenAIAdapter(api_key=None)
            with pytest.raises(MissingAPIKeyError):
                adapter._configure()


# =============================================================================
# Successful generation
# =============================================================================


class TestOpenAIAdapterSuccess:
    @pytest.mark.asyncio
    async def test_generate_response_returns_string(self, mock_settings):
        with patch("src.infra.llm.openai_adapter.get_settings", return_value=mock_settings):
            from src.infra.llm.openai_adapter import OpenAIAdapter

            adapter = OpenAIAdapter(api_key="sk-valid")
            adapter._configured = True  # skip real _configure

            # Build a mock response mimicking openai ChatCompletion
            mock_choice = MagicMock()
            mock_choice.message.content = "Hello, world!"
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            adapter._client = mock_client
            adapter._settings = mock_settings

            result = await adapter.generate_response("Say hi")
            assert isinstance(result, str)
            assert result == "Hello, world!"


# =============================================================================
# Rate limit handling
# =============================================================================


class TestOpenAIAdapterRateLimit:
    @pytest.mark.asyncio
    async def test_429_maps_to_llm_rate_limit_error(self, mock_settings):
        with patch("src.infra.llm.openai_adapter.get_settings", return_value=mock_settings):
            from src.core.exceptions import LLMRateLimitError
            from src.infra.llm.openai_adapter import OpenAIAdapter

            adapter = OpenAIAdapter(api_key="sk-valid")
            adapter._configured = True

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("429 rate_limit exceeded")
            )
            adapter._client = mock_client
            adapter._settings = mock_settings

            with pytest.raises(LLMRateLimitError):
                await adapter.generate_response("hi")


# =============================================================================
# Connection error handling
# =============================================================================


class TestOpenAIAdapterConnectionError:
    @pytest.mark.asyncio
    async def test_connection_error_maps_correctly(self, mock_settings):
        with patch("src.infra.llm.openai_adapter.get_settings", return_value=mock_settings):
            from src.core.exceptions import LLMConnectionError
            from src.infra.llm.openai_adapter import OpenAIAdapter

            adapter = OpenAIAdapter(api_key="sk-valid")
            adapter._configured = True

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=Exception("connection error: network unreachable")
            )
            adapter._client = mock_client
            adapter._settings = mock_settings

            with pytest.raises(LLMConnectionError):
                await adapter.generate_response("hi")
