import pytest
import os
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import turbovec
import aiosqlite
from src.core.config import Settings
from src.infra.turbovec_memory import TurbovecMemoryService

@pytest.fixture
def temp_settings():
    with tempfile.TemporaryDirectory() as td:
        settings = Settings()
        settings.MEMORY_ENABLED = True
        settings.MEMORY_PERSIST_DIR = td
        settings.GEMINI_API_KEY = "test-key"
        yield settings

@pytest.fixture
def mock_turbovec_service(temp_settings):
    service = TurbovecMemoryService(settings=temp_settings)
    
    # Mock embedding to avoid external calls
    async def _mock_embed(text, task_type="retrieval_document"):
        # Match whatever dimension the service decided on
        return [0.1] * service._embed_dim
        
    service._embed_async = _mock_embed
    
    return service

@pytest.mark.asyncio
async def test_turbovec_initialization(mock_turbovec_service):
    # Ensure no global conflicts by patching the globals for the test
    with patch("src.infra.turbovec_memory._global_turbovec_index", None):
        await mock_turbovec_service.initialize()
        
        assert mock_turbovec_service.is_enabled
        assert mock_turbovec_service._db is not None
        assert mock_turbovec_service._index is not None
        
        # Verify db file created
        assert mock_turbovec_service._db_path.exists()
        
        # Verify tables created
        async with mock_turbovec_service._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_payloads'") as cursor:
            assert await cursor.fetchone() is not None

@pytest.mark.asyncio
async def test_turbovec_store_and_retrieve(mock_turbovec_service):
    with patch("src.infra.turbovec_memory._global_turbovec_index", None):
        await mock_turbovec_service.initialize()
        
        # Store memory
        success = await mock_turbovec_service.store(
            session_id="test_session",
            role="user",
            text="I love testing with pytest"
        )
        assert success
        
        # Retrieve memory
        results = await mock_turbovec_service.retrieve("What do I love?")
        assert len(results) == 1
        assert results[0].text == "I love testing with pytest"
        assert results[0].session_id == "test_session"
        assert results[0].role == "user"

@pytest.mark.asyncio
async def test_turbovec_clear_session(mock_turbovec_service):
    with patch("src.infra.turbovec_memory._global_turbovec_index", None):
        await mock_turbovec_service.initialize()
        
        # Store 2 memories for session A, 1 for session B
        await mock_turbovec_service.store(session_id="session_A", role="user", text="A1")
        await mock_turbovec_service.store(session_id="session_A", role="user", text="A2")
        await mock_turbovec_service.store(session_id="session_B", role="user", text="B1")
        
        assert mock_turbovec_service.memory_count == 3
        
        # Clear session A
        deleted_count = await mock_turbovec_service.clear_session("session_A")
        assert deleted_count == 2
        assert mock_turbovec_service.memory_count == 1
        
        # Only B should remain
        results = await mock_turbovec_service.retrieve("B1")
        assert len(results) == 1
        assert results[0].session_id == "session_B"

@pytest.mark.asyncio
async def test_turbovec_delete_by_text(mock_turbovec_service):
    with patch("src.infra.turbovec_memory._global_turbovec_index", None):
        await mock_turbovec_service.initialize()
        
        await mock_turbovec_service.store(session_id="session_A", role="user", text="forget me")
        await mock_turbovec_service.store(session_id="session_A", role="user", text="keep me")
        
        deleted = await mock_turbovec_service.delete_by_text("forget me")
        assert deleted == 1
        
        results = await mock_turbovec_service.retrieve("forget")
        assert len(results) == 1
        assert results[0].text == "keep me"
