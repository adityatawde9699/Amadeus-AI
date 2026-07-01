"""
Integration tests for LLM Router fallback chain.

Tests verify the Groq → Gemini → OpenAI provider cascade,
including Redis quota tracking and graceful degradation.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# Stub heavy imports
for _mod in ("joblib", "google.generativeai", "openai", "groq"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)


def _make_mock_adapter(name: str, response: str = "ok") -> MagicMock:
    adapter = MagicMock()
    adapter.generate_response = AsyncMock(return_value=response)
    return adapter


def _make_rate_limited_adapter(name: str) -> MagicMock:
    from src.core.exceptions import LLMRateLimitError

    adapter = MagicMock()
    adapter.generate_response = AsyncMock(side_effect=LLMRateLimitError(name))
    return adapter


# =============================================================================
# Fallback chain
# =============================================================================


class TestLLMRouterFallback:
    """Verify that the router falls through providers when rate-limited."""

    @pytest.mark.asyncio
    async def test_falls_back_groq_to_gemini(self):
        from src.infra.llm.router import LLMRouter

        groq = _make_rate_limited_adapter("groq")
        gemini = _make_mock_adapter("gemini", "gemini response")

        router = LLMRouter(groq=groq, gemini=gemini)
        text, provider = await router.generate("test prompt")

        assert provider == "gemini"
        assert text == "gemini response"

    @pytest.mark.asyncio
    async def test_falls_back_gemini_to_openai(self):
        from src.infra.llm.router import LLMRouter

        groq = _make_rate_limited_adapter("groq")
        gemini = _make_rate_limited_adapter("gemini")
        openai = _make_mock_adapter("openai", "openai response")

        router = LLMRouter(groq=groq, gemini=gemini, openai=openai)
        # complexity="high" enables openai as a candidate
        text, provider = await router.generate("complex task", complexity="high")

        assert provider == "openai"
        assert text == "openai response"

    @pytest.mark.asyncio
    async def test_all_exhausted_raises_rate_limit_error(self):
        from src.core.exceptions import LLMRateLimitError
        from src.infra.llm.router import LLMRouter

        groq = _make_rate_limited_adapter("groq")
        gemini = _make_rate_limited_adapter("gemini")
        openai = _make_rate_limited_adapter("openai")

        router = LLMRouter(groq=groq, gemini=gemini, openai=openai)

        with pytest.raises(LLMRateLimitError):
            await router.generate("test", complexity="high")

    @pytest.mark.asyncio
    async def test_daily_limit_in_memory_skips_provider(self):
        """Provider at daily limit should be skipped without hitting the adapter."""
        from src.infra.llm.router import LLMRouter

        groq = _make_mock_adapter("groq", "should not be called")
        gemini = _make_mock_adapter("gemini", "from gemini")

        router = LLMRouter(groq=groq, gemini=gemini)
        # Saturate groq's counter
        router._usage["groq"] = router.DAILY_LIMITS["groq"]

        _text, provider = await router.generate("test")
        assert provider == "gemini"
        groq.generate_response.assert_not_called()


# =============================================================================
# Redis quota integration
# =============================================================================


class TestLLMRouterRedisQuota:
    @pytest.mark.asyncio
    async def test_redis_backend_initialised_when_url_given(self):
        from src.infra.llm.router import LLMRouter, _RedisCounterBackend

        router = LLMRouter(redis_url="redis://localhost:6379/0")
        assert router._redis is not None
        assert isinstance(router._redis, _RedisCounterBackend)

    @pytest.mark.asyncio
    async def test_router_uses_redis_count_over_memory(self):
        """If Redis says groq usage > in-memory, Redis count wins and groq is skipped."""
        from src.infra.llm.router import LLMRouter

        groq = _make_mock_adapter("groq", "groq ok")
        gemini = _make_mock_adapter("gemini", "gemini ok")

        router = LLMRouter(groq=groq, gemini=gemini, redis_url="redis://localhost:6379/0")

        # Simulate Redis reporting groq at limit, but gemini at 0
        groq_limit = LLMRouter.DAILY_LIMITS["groq"]

        async def redis_get(provider: str) -> int:
            return groq_limit if provider == "groq" else 0

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=redis_get)
        mock_redis.increment = AsyncMock()
        router._redis = mock_redis

        _text, provider = await router.generate("test")
        # Should skip groq (Redis says at limit) and fall to gemini
        assert provider == "gemini"
        groq.generate_response.assert_not_called()
