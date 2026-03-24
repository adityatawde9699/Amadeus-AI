"""
Unit tests for OllamaAdapter — local LLM inference adapter.

All tests use mocked httpx responses — no real Ollama server required.
Test style matches existing test_memory_agent_integration.py conventions.
"""

from __future__ import annotations

import json
import sys
import types
from asyncio import Queue
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================
# Stub heavy imports if needed
# ===========================
for _mod in ("google.generativeai", "groq", "sklearn"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)


# ==========================================================================
# Helpers
# ==========================================================================

def _make_json_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with a JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def _make_stream_lines(chunks: list[dict]) -> AsyncIterator[str]:
    """Create an async iterable of NDJSON lines for streaming tests."""
    async def _gen():
        for chunk in chunks:
            yield json.dumps(chunk)
    return _gen()


# ==========================================================================
# Tests
# ==========================================================================

class TestOllamaAdapterAvailability:
    """Tests for is_available() and is_server_running()."""

    @pytest.mark.asyncio
    async def test_is_available_true_when_model_present(self):
        """Returns True when Ollama is running and model is listed."""
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        mock_resp = _make_json_response(
            {"models": [{"name": "phi3:mini"}, {"name": "llama3.2:3b"}]}
        )
        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            result = await adapter.is_available()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_available_false_when_model_missing(self):
        """Returns False when Ollama runs but model is not downloaded."""
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        mock_resp = _make_json_response({"models": [{"name": "llama3.2:3b"}]})
        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            result = await adapter.is_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_available_false_when_server_down(self):
        """Returns False when Ollama server is not running (connection error)."""
        import httpx
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_fn.return_value = mock_client

            result = await adapter.is_available()

        assert result is False


class TestOllamaAdapterGeneration:
    """Tests for generate_response()."""

    @pytest.mark.asyncio
    async def test_generate_response_returns_text(self):
        """generate_response returns the 'response' field from Ollama."""
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        generate_resp = _make_json_response(
            {"response": "Hello! I am Phi-3 Mini.", "eval_count": 12, "done": True}
        )
        server_resp = MagicMock()
        server_resp.status_code = 200

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            # First call is is_server_running() GET /
            mock_client.get = AsyncMock(return_value=server_resp)
            # Second call is POST /api/generate
            mock_client.post = AsyncMock(return_value=generate_resp)
            mock_client_fn.return_value = mock_client

            result = await adapter.generate_response("Hello!")

        assert result == "Hello! I am Phi-3 Mini."

    @pytest.mark.asyncio
    async def test_generate_response_raises_when_ollama_down(self):
        """Raises LLMRateLimitError if Ollama server is not running."""
        import httpx
        from src.core.exceptions import LLMRateLimitError
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_fn.return_value = mock_client

            with pytest.raises(LLMRateLimitError, match="Ollama server not running"):
                await adapter.generate_response("Hello!")

    @pytest.mark.asyncio
    async def test_generate_respects_temperature(self):
        """Temperature parameter is passed through to Ollama payload."""
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        generate_resp = _make_json_response(
            {"response": "Deterministic answer.", "done": True}
        )
        server_resp = MagicMock()
        server_resp.status_code = 200
        captured_payloads: list[dict] = []

        async def capture_post(path, json=None, **kwargs):
            captured_payloads.append(json or {})
            return generate_resp

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=server_resp)
            mock_client.post = AsyncMock(side_effect=capture_post)
            mock_client_fn.return_value = mock_client

            await adapter.generate_response("Hello!", temperature=0.0)

        assert captured_payloads[0]["options"]["temperature"] == 0.0


class TestOllamaAdapterStreaming:
    """Tests for stream_response() token-by-token generation."""

    @pytest.mark.asyncio
    async def test_stream_response_yields_tokens(self):
        """stream_response yields individual token strings from Ollama."""
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")
        server_resp = MagicMock()
        server_resp.status_code = 200

        stream_chunks = [
            {"response": "Hello", "done": False},
            {"response": " world", "done": False},
            {"response": "!", "done": True},
        ]

        class _FakeStream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            def raise_for_status(self):
                pass
            async def aiter_lines(self):
                for chunk in stream_chunks:
                    yield json.dumps(chunk)

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=server_resp)
            mock_client.stream = MagicMock(return_value=_FakeStream())
            mock_client_fn.return_value = mock_client

            tokens = []
            async for token in adapter.stream_response("Hello!"):
                tokens.append(token)

        assert tokens == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_stream_response_graceful_when_server_down(self):
        """stream_response yields error message instead of crashing."""
        import httpx
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Server down")
            )
            mock_client_fn.return_value = mock_client

            tokens = []
            async for token in adapter.stream_response("Hello!"):
                tokens.append(token)

        # Should not crash — should yield a single warning message
        assert len(tokens) == 1
        assert "Ollama" in tokens[0] or "⚠️" in tokens[0]


class TestOllamaAdapterModelManagement:
    """Tests for list_models() and pull_model()."""

    @pytest.mark.asyncio
    async def test_list_models_returns_model_objects(self):
        """list_models returns OllamaModel instances with correct attributes."""
        from src.infra.llm.ollama_adapter import OllamaAdapter, OllamaModel

        adapter = OllamaAdapter(model="phi3:mini")
        mock_resp = _make_json_response({
            "models": [
                {
                    "name": "phi3:mini",
                    "size": 2_300_000_000,
                    "modified_at": "2024-12-01T00:00:00Z",
                    "digest": "abc123",
                },
                {
                    "name": "llama3.2:3b",
                    "size": 2_000_000_000,
                    "modified_at": "2024-11-15T00:00:00Z",
                    "digest": "def456",
                },
            ]
        })

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_fn.return_value = mock_client

            models = await adapter.list_models()

        assert len(models) == 2
        assert isinstance(models[0], OllamaModel)
        assert models[0].name == "phi3:mini"
        assert models[0].size_gb == pytest.approx(2.14, abs=0.1)

    @pytest.mark.asyncio
    async def test_list_models_returns_empty_on_error(self):
        """list_models returns empty list if Ollama is unreachable."""
        import httpx
        from src.infra.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(model="phi3:mini")

        with patch.object(adapter, "_get_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Refused")
            )
            mock_client_fn.return_value = mock_client

            models = await adapter.list_models()

        assert models == []


class TestLLMRouterWithOllama:
    """Tests for LLMRouter with Ollama as priority-0 provider."""

    @pytest.mark.asyncio
    async def test_router_prefers_ollama_over_groq(self):
        """Router calls Ollama first, before Groq."""
        import sys
        import types as _types

        # Stub modules for router import
        for mod in ("joblib", "redis", "redis.asyncio"):
            if mod not in sys.modules:
                sys.modules[mod] = _types.ModuleType(mod)

        from src.infra.llm.router import LLMRouter

        ollama = AsyncMock()
        ollama.generate_response = AsyncMock(return_value="Local response")
        groq = AsyncMock()
        groq.generate_response = AsyncMock(return_value="Cloud response")

        router = LLMRouter(ollama=ollama, groq=groq)  # type: ignore
        response, provider = await router.generate("Hello!")

        assert response == "Local response"
        assert provider == "ollama"
        groq.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_router_falls_back_to_groq_when_ollama_fails(self):
        """Router falls back to Groq when Ollama raises LLMRateLimitError."""
        import sys
        import types as _types
        from src.core.exceptions import LLMRateLimitError

        for mod in ("joblib", "redis", "redis.asyncio"):
            if mod not in sys.modules:
                sys.modules[mod] = _types.ModuleType(mod)

        from src.infra.llm.router import LLMRouter

        ollama = AsyncMock()
        ollama.generate_response = AsyncMock(
            side_effect=LLMRateLimitError("Ollama not running")
        )
        groq = AsyncMock()
        groq.generate_response = AsyncMock(return_value="Groq fallback")

        router = LLMRouter(ollama=ollama, groq=groq)  # type: ignore
        response, provider = await router.generate("Hello!")

        assert response == "Groq fallback"
        assert provider == "groq"

    @pytest.mark.asyncio
    async def test_local_only_mode_disables_cloud(self):
        """LOCAL_ONLY_MODE prevents cloud providers from being registered."""
        import sys
        import types as _types

        for mod in ("joblib", "redis", "redis.asyncio"):
            if mod not in sys.modules:
                sys.modules[mod] = _types.ModuleType(mod)

        from src.infra.llm.router import LLMRouter

        ollama = AsyncMock()
        ollama.generate_response = AsyncMock(return_value="Local only!")
        groq = AsyncMock()

        router = LLMRouter(ollama=ollama, groq=groq, local_only_mode=True)  # type: ignore

        # Groq should not be in providers
        assert "groq" not in router._providers
        assert "ollama" in router._providers
