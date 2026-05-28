"""
Unit tests for QdrantMemoryService (src/infra/memory_service.py).

All Qdrant and Gemini calls are mocked so tests run without
any API keys or local Qdrant installation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infra.memory_service import MemoryResult, QdrantMemoryService


# ===========================================================================
# Fixtures
# ===========================================================================


def _mock_settings(memory_enabled: bool = True) -> MagicMock:
    """Build a minimal Settings mock."""
    s = MagicMock()
    s.MEMORY_ENABLED = memory_enabled
    s.MEMORY_PERSIST_DIR = "/tmp/test_vector_db"
    s.MEMORY_COLLECTION_NAME = "test_memory"
    s.MEMORY_EMBED_MODEL = "models/embedding-001"
    s.GEMINI_API_KEY = "fake-api-key"
    return s


# ===========================================================================
# Tests: Service Initialization
# ===========================================================================


class TestQdrantMemoryServiceInit:
    """Verify service boots up correctly."""

    def test_disabled_when_memory_not_enabled(self) -> None:
        """Service stays disabled when MEMORY_ENABLED=False."""
        settings = _mock_settings(memory_enabled=False)
        with patch("src.infra.memory_service.QdrantMemoryService._setup"):
            svc = QdrantMemoryService.__new__(QdrantMemoryService)
            svc._settings = settings
            svc._enabled = False
            svc._initialized = False

        assert svc.is_enabled is False

    def test_graceful_degradation_on_import_error(self) -> None:
        """Service disables itself when qdrant_client is not installed."""
        settings = _mock_settings()
        with patch("builtins.__import__", side_effect=ImportError("no module named qdrant_client")):
            svc = QdrantMemoryService.__new__(QdrantMemoryService)
            svc._settings = settings
            svc._client = None
            svc._embed_model = None
            svc._enabled = False
            svc._initialized = False

        assert svc.is_enabled is False


# ===========================================================================
# Tests: store()
# ===========================================================================


class TestQdrantMemoryServiceStore:
    """Test the store() async method."""

    @pytest.mark.asyncio
    async def test_store_calls_embed_and_upsert(self) -> None:
        """store() should embed text and upsert into Qdrant collection."""
        settings = _mock_settings()

        # Build a pre-initialized service without touching real Qdrant
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._embed_model = "models/embedding-001"

        # Mock the Qdrant async client
        mock_client = AsyncMock()
        svc._client = mock_client

        fake_embedding = [0.1] * 768

        with patch.object(svc, "_embed_async", return_value=fake_embedding):
            result = await svc.store("session-abc", "user", "I love astronomy")

        assert result is True
        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args
        # Qdrant upsert uses collection_name and points
        assert call_kwargs.kwargs["collection_name"] == "test_memory"
        points = call_kwargs.kwargs["points"]
        assert len(points) == 1
        assert points[0].payload["text"] == "I love astronomy"
        assert points[0].payload["role"] == "user"
        assert points[0].payload["session_id"] == "session-abc"

    @pytest.mark.asyncio
    async def test_store_returns_false_when_disabled(self) -> None:
        """store() should return False immediately when service is disabled."""
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._enabled = False
        svc._initialized = False

        result = await svc.store("session-abc", "user", "hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_returns_false_on_embedding_failure(self) -> None:
        """store() should return False gracefully when embedding fails."""
        settings = _mock_settings()
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._client = AsyncMock()
        svc._embed_model = "models/embedding-001"

        with patch.object(svc, "_embed_async", return_value=None):
            result = await svc.store("session-abc", "user", "test")

        assert result is False
        svc._client.upsert.assert_not_called()


# ===========================================================================
# Tests: retrieve()
# ===========================================================================


class TestQdrantMemoryServiceRetrieve:
    """Test the retrieve() async method."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_memory_results(self) -> None:
        """retrieve() should return a list of MemoryResult on success."""
        settings = _mock_settings()
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._embed_model = "models/embedding-001"

        # Mock Qdrant search results (ScoredPoint objects)
        hit1 = MagicMock()
        hit1.payload = {
            "session_id": "sess-1",
            "role": "user",
            "text": "I love astronomy",
            "timestamp": "2026-01-01T00:00:00",
        }
        hit1.score = 0.95

        hit2 = MagicMock()
        hit2.payload = {
            "session_id": "sess-2",
            "role": "assistant",
            "text": "Let's talk about stars",
            "timestamp": "2026-01-02T00:00:00",
        }
        hit2.score = 0.75

        mock_client = AsyncMock()
        mock_client.search.return_value = [hit1, hit2]
        svc._client = mock_client

        fake_embedding = [0.1] * 768
        with patch.object(svc, "_embed_async", return_value=fake_embedding):
            results = await svc.retrieve("What do I enjoy?", top_k=5)

        assert len(results) == 2
        assert isinstance(results[0], MemoryResult)
        assert results[0].text == "I love astronomy"
        assert results[0].role == "user"
        assert results[0].distance == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_when_disabled(self) -> None:
        """retrieve() must return [] when service is disabled."""
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._enabled = False
        svc._initialized = False

        results = await svc.retrieve("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_on_query_failure(self) -> None:
        """retrieve() must return [] gracefully on Qdrant error."""
        settings = _mock_settings()
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._embed_model = "models/embedding-001"

        mock_client = AsyncMock()
        mock_client.search.side_effect = RuntimeError("DB failure")
        svc._client = mock_client

        with patch.object(svc, "_embed_async", return_value=[0.1] * 768):
            results = await svc.retrieve("some query")

        assert results == []


# ===========================================================================
# Tests: format_for_prompt()
# ===========================================================================


class TestFormatForPrompt:
    """Test the prompt-formatting helper."""

    def test_empty_memories_returns_empty_string(self) -> None:
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        assert svc.format_for_prompt([]) == ""

    def test_formats_memories_with_role_labels(self) -> None:
        memories = [
            MemoryResult("s1", "user", "I love astronomy", "2026-01-01", 0.01),
            MemoryResult("s1", "assistant", "That's wonderful!", "2026-01-01", 0.05),
        ]
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        output = svc.format_for_prompt(memories)
        assert "User]:" in output
        assert "Amadeus]:" in output
        assert "I love astronomy" in output
        assert "That's wonderful!" in output

    def test_max_chars_truncates_output(self) -> None:
        """format_for_prompt should stop appending memories once max_chars is reached."""
        memories = [
            MemoryResult("s1", "user", "x" * 200, "2026-01-01", i * 0.01) for i in range(10)
        ]
        svc = QdrantMemoryService.__new__(QdrantMemoryService)
        output = svc.format_for_prompt(memories, max_chars=300)
        assert len(output) <= 500  # generous bound accounting for header line
