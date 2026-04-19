from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.infra.search.search_router import SearchRouter


@pytest.fixture
def search_router():
    return SearchRouter(tavily_api_key="test_tavily")


@pytest.mark.asyncio
async def test_search_wikipedia_factual(search_router):
    with patch.object(search_router, "_wikipedia_search", new_callable=AsyncMock) as mock_wiki:
        mock_wiki.return_value = (
            "Wikipedia summary that is definitely longer than 80 characters. " * 3
        )
        # Since it's a factual query, wiki should be called first
        result = await search_router.search("who is Albert Einstein")
        mock_wiki.assert_called_once_with("who is Albert Einstein")
        assert result.startswith("Wikipedia")


