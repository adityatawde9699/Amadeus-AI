"""
Unit tests for ChromaMemoryService (src/infra/memory_service.py).

All ChromaDB and Gemini calls are mocked so tests run without
any API keys or local ChromaDB installation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infra.memory_service import ChromaMemoryService, MemoryResult


# ===========================================================================
# Fixtures
# ===========================================================================

def _mock_settings(chroma_enabled: bool = True) -> MagicMock:
    """Build a minimal Settings mock."""
    s = MagicMock()
    s.CHROMA_ENABLED = chroma_enabled
    s.CHROMA_PERSIST_DIR = "/tmp/test_chroma"
    s.CHROMA_COLLECTION_NAME = "test_memory"
    s.MEMORY_EMBED_MODEL = "models/embedding-001"
    s.GEMINI_API_KEY = "fake-api-key"
    return s


# ===========================================================================
# Tests: Service Initialization
# ===========================================================================

class TestChromeMemoryServiceInit:
    """Verify service boots up correctly."""

    def test_disabled_when_chroma_not_enabled(self) -> None:
        """Service stays disabled when CHROMA_ENABLED=False."""
        settings = _mock_settings(chroma_enabled=False)
        with patch("src.infra.memory_service.ChromaMemoryService._setup"):
            svc = ChromaMemoryService.__new__(ChromaMemoryService)
            svc._settings = settings
            svc._enabled = False
            svc._initialized = False

        assert svc._enabled is False

    def test_graceful_degradation_on_import_error(self) -> None:
        """Service disables itself when chromadb is not installed."""
        settings = _mock_settings()
        with patch("builtins.__import__", side_effect=ImportError("no module named chromadb")):
            # Patching _setup to simulate an ImportError scenario
            svc = ChromaMemoryService.__new__(ChromaMemoryService)
            svc._settings = settings
            svc._client = None
            svc._collection = None
            svc._embed_model = None
            svc._enabled = False
            svc._initialized = False

        assert svc.is_enabled is False


# ===========================================================================
# Tests: store()
# ===========================================================================

class TestChromeMemoryServiceStore:
    """Test the store() async method."""

    @pytest.mark.asyncio
    async def test_store_calls_embed_and_upsert(self) -> None:
        """store() should embed text and upsert into ChromaDB collection."""
        settings = _mock_settings()

        # Build a pre-initialized service without touching real ChromaDB
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True

        mock_collection = MagicMock()
        svc._collection = mock_collection
        svc._embed_model = "models/embedding-001"

        fake_embedding = [0.1] * 768

        with patch.object(svc, "_embed", return_value=fake_embedding):
            result = await svc.store("session-abc", "user", "I love astronomy")

        assert result is True
        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args
        assert call_kwargs.kwargs["documents"] == ["I love astronomy"]
        assert call_kwargs.kwargs["metadatas"][0]["role"] == "user"
        assert call_kwargs.kwargs["metadatas"][0]["session_id"] == "session-abc"

    @pytest.mark.asyncio
    async def test_store_returns_false_when_disabled(self) -> None:
        """store() should return False immediately when service is disabled."""
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._enabled = False
        svc._initialized = False

        result = await svc.store("session-abc", "user", "hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_returns_false_on_embedding_failure(self) -> None:
        """store() should return False gracefully when embedding fails."""
        settings = _mock_settings()
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._collection = MagicMock()
        svc._embed_model = "models/embedding-001"

        with patch.object(svc, "_embed", return_value=None):
            result = await svc.store("session-abc", "user", "test")

        assert result is False
        svc._collection.upsert.assert_not_called()


# ===========================================================================
# Tests: retrieve()
# ===========================================================================

class TestChromeMemoryServiceRetrieve:
    """Test the retrieve() async method."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_memory_results(self) -> None:
        """retrieve() should return a list of MemoryResult on success."""
        settings = _mock_settings()
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._embed_model = "models/embedding-001"

        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "documents": [["I love astronomy", "Let's talk about stars"]],
            "metadatas": [
                [
                    {"session_id": "sess-1", "role": "user",      "timestamp": "2026-01-01T00:00:00"},
                    {"session_id": "sess-2", "role": "assistant", "timestamp": "2026-01-02T00:00:00"},
                ]
            ],
            "distances": [[0.05, 0.25]],
        }
        svc._collection = mock_collection

        fake_embedding = [0.1] * 768
        with patch.object(svc, "_embed_query", return_value=fake_embedding):
            results = await svc.retrieve("What do I enjoy?", top_k=5)

        assert len(results) == 2
        assert isinstance(results[0], MemoryResult)
        assert results[0].text == "I love astronomy"
        assert results[0].role == "user"
        assert results[0].distance == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_when_disabled(self) -> None:
        """retrieve() must return [] when service is disabled."""
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._enabled = False
        svc._initialized = False

        results = await svc.retrieve("query")
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_on_query_failure(self) -> None:
        """retrieve() must return [] gracefully on ChromaDB error."""
        settings = _mock_settings()
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        svc._settings = settings
        svc._enabled = True
        svc._initialized = True
        svc._embed_model = "models/embedding-001"
        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.query.side_effect = RuntimeError("DB failure")
        svc._collection = mock_collection

        with patch.object(svc, "_embed_query", return_value=[0.1] * 768):
            results = await svc.retrieve("some query")

        assert results == []


# ===========================================================================
# Tests: format_for_prompt()
# ===========================================================================

class TestFormatForPrompt:
    """Test the prompt-formatting helper."""

    def test_empty_memories_returns_empty_string(self) -> None:
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        assert svc.format_for_prompt([]) == ""

    def test_formats_memories_with_role_labels(self) -> None:
        memories = [
            MemoryResult("s1", "user", "I love astronomy", "2026-01-01", 0.01),
            MemoryResult("s1", "assistant", "That's wonderful!", "2026-01-01", 0.05),
        ]
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        output = svc.format_for_prompt(memories)
        assert "User]:" in output
        assert "Amadeus]:" in output
        assert "I love astronomy" in output
        assert "That's wonderful!" in output

    def test_max_chars_truncates_output(self) -> None:
        """format_for_prompt should stop appending memories once max_chars is reached."""
        memories = [MemoryResult("s1", "user", "x" * 200, "2026-01-01", i * 0.01) for i in range(10)]
        svc = ChromaMemoryService.__new__(ChromaMemoryService)
        output = svc.format_for_prompt(memories, max_chars=300)
        assert len(output) <= 500  # generous bound accounting for header line
