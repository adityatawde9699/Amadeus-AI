import pytest
from unittest.mock import AsyncMock, patch
from src.infra.search.search_router import SearchRouter
from datetime import date, timedelta

@pytest.fixture
def search_router():
    return SearchRouter(brave_api_key="test_brave", tavily_api_key="test_tavily")

@pytest.mark.asyncio
async def test_search_wikipedia_factual(search_router):
    with patch.object(search_router, "_wikipedia_search", new_callable=AsyncMock) as mock_wiki:
        mock_wiki.return_value = "Wikipedia summary that is definitely longer than 80 characters. " * 3
        # Since it's a factual query, wiki should be called first
        result = await search_router.search("who is Albert Einstein")
        mock_wiki.assert_called_once_with("who is Albert Einstein")
        assert result.startswith("Wikipedia")

@pytest.mark.asyncio
async def test_search_brave_fallback(search_router):
    with patch.object(search_router, "_wikipedia_search", new_callable=AsyncMock) as mock_wiki, \
         patch.object(search_router, "_ddg_search", new_callable=AsyncMock) as mock_ddg, \
         patch.object(search_router, "_brave_search", new_callable=AsyncMock) as mock_brave:
        
        mock_wiki.return_value = ""
        mock_ddg.return_value = ""
        mock_brave.return_value = "Brave search results"
        
        result = await search_router.search("general query")
        mock_brave.assert_called_once()
        assert result == "Brave search results"
        assert search_router._brave_daily_count == 1

@pytest.mark.asyncio
async def test_daily_limit_reset(search_router):
    search_router._brave_daily_count = 60
    search_router._count_date = date.today() - timedelta(days=1)
    
    with patch.object(search_router, "_ddg_search", new_callable=AsyncMock) as mock_ddg, \
         patch.object(search_router, "_brave_search", new_callable=AsyncMock) as mock_brave:
        mock_ddg.return_value = ""
        mock_brave.return_value = "Brave results"
        
        await search_router.search("test")
        assert search_router._brave_daily_count == 1
        assert search_router._count_date == date.today()
        assert search_router._force_free_search is False
