import pytest
from unittest.mock import AsyncMock, patch
from src.infra.cache.cache_service import CacheService

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    return redis

@pytest.fixture
def cache_service(mock_redis):
    # Initialize CacheService with our mock redis client
    return CacheService(redis=mock_redis)

@pytest.mark.asyncio
async def test_set_llm(cache_service, mock_redis):
    await cache_service.set_llm("test_input", "test_output", "gemini")
    mock_redis.setex.assert_called_once()
    assert cache_service._hits == 0

@pytest.mark.asyncio
async def test_get_llm_hit(cache_service, mock_redis):
    mock_redis.get.return_value = "cached_response"
    result = await cache_service.get_llm("test_input", "gemini")
    assert result == "cached_response"
    assert cache_service._hits == 1
    assert cache_service._misses == 0

@pytest.mark.asyncio
async def test_get_llm_miss(cache_service, mock_redis):
    mock_redis.get.return_value = None
    result = await cache_service.get_llm("test_input", "gemini")
    assert result is None
    assert cache_service._hits == 0
    assert cache_service._misses == 1

@pytest.mark.asyncio
async def test_set_tts(cache_service, mock_redis):
    await cache_service.set_tts("hello", "voice1", b"audio")
    mock_redis.setex.assert_called_once()

@pytest.mark.asyncio
async def test_get_tts(cache_service, mock_redis):
    mock_redis.get.return_value = b"audio"
    result = await cache_service.get_tts("hello", "voice1")
    assert result == b"audio"
    assert cache_service._hits == 1

def test_cache_stats(cache_service, mock_redis):
    cache_service._hits = 5
    cache_service._misses = 5
    stats = cache_service.get_stats()
    assert stats["hits"] == 5
    assert stats["misses"] == 5
    assert stats["total"] == 10
    assert stats["hit_rate_pct"] == 50.0
