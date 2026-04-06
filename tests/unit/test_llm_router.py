"""
Unit tests for LLMRouter.

Tests cover:
- Provider fallback chain (groq → gemini → openai)
- Daily limit enforcement
- Usage counter increments correctly (thread-safe via asyncio.Lock)
- LLMRateLimitError raised when all providers exhausted
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.core.exceptions import LLMRateLimitError
from src.infra.llm.router import LLMRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_provider(response: str = "ok") -> AsyncMock:
    provider = AsyncMock()
    provider.generate_response = AsyncMock(return_value=response)
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLLMRouterFallback:
    @pytest.mark.asyncio
    async def test_uses_groq_first(self):
        """Groq (primary) is tried before gemini."""
        groq = _make_mock_provider("groq-response")
        gemini = _make_mock_provider("gemini-response")
        router = LLMRouter(groq=groq, gemini=gemini)

        result, provider = await router.generate("hello")

        assert provider == "groq"
        assert result == "groq-response"
        groq.generate_response.assert_called_once()
        gemini.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_gemini_when_groq_fails(self):
        """If Groq raises an exception, Gemini is tried next."""
        groq = AsyncMock()
        groq.generate_response = AsyncMock(side_effect=Exception("Groq down"))
        gemini = _make_mock_provider("gemini-response")
        router = LLMRouter(groq=groq, gemini=gemini)

        result, provider = await router.generate("hello")

        assert provider == "gemini"
        assert result == "gemini-response"

    @pytest.mark.asyncio
    async def test_raises_when_all_providers_fail(self):
        """LLMRateLimitError is raised when all providers fail."""
        groq = AsyncMock()
        groq.generate_response = AsyncMock(side_effect=Exception("fail"))
        gemini = AsyncMock()
        gemini.generate_response = AsyncMock(side_effect=Exception("fail"))
        router = LLMRouter(groq=groq, gemini=gemini)

        with pytest.raises(LLMRateLimitError):
            await router.generate("hello")

    @pytest.mark.asyncio
    async def test_daily_limit_skips_provider(self):
        """A provider at its daily limit is skipped."""
        groq = _make_mock_provider("groq-response")
        gemini = _make_mock_provider("gemini-response")
        router = LLMRouter(groq=groq, gemini=gemini)

        # Manually simulate groq hitting its limit
        router._usage["groq"] = LLMRouter.DAILY_LIMITS["groq"]

        result, provider = await router.generate("hello")

        assert provider == "gemini"
        groq.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_openai_only_used_for_high_complexity(self):
        """OpenAI is only included in the fallback chain for high-complexity requests."""
        groq = AsyncMock()
        groq.generate_response = AsyncMock(side_effect=Exception("fail"))
        gemini = AsyncMock()
        gemini.generate_response = AsyncMock(side_effect=Exception("fail"))
        openai = _make_mock_provider("openai-response")
        router = LLMRouter(groq=groq, gemini=gemini, openai=openai)

        # Normal complexity — openai should NOT be tried
        with pytest.raises(LLMRateLimitError):
            await router.generate("hello", complexity="normal")

        # High complexity — openai IS tried
        result, provider = await router.generate("complex analysis", complexity="high")
        assert provider == "openai"


class TestLLMRouterUsageCounter:
    @pytest.mark.asyncio
    async def test_usage_increments_on_success(self):
        """Usage counter increments after a successful generation."""
        groq = _make_mock_provider("ok")
        router = LLMRouter(groq=groq)

        assert router._usage["groq"] == 0
        await router.generate("ping")
        assert router._usage["groq"] == 1
        await router.generate("pong")
        assert router._usage["groq"] == 2

    @pytest.mark.asyncio
    async def test_usage_not_incremented_on_failure(self):
        """Usage counter does NOT increment when the provider raises an error."""
        groq = AsyncMock()
        groq.generate_response = AsyncMock(side_effect=Exception("fail"))
        gemini = _make_mock_provider("ok")
        router = LLMRouter(groq=groq, gemini=gemini)

        await router.generate("hello")
        # groq failed — its counter stays 0; gemini succeeded — its counter is 1
        assert router._usage["groq"] == 0
        assert router._usage["gemini"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_usage_increments_are_safe(self):
        """Concurrent calls should not corrupt usage counters (asyncio.Lock)."""
        call_count = 0

        async def slow_generate(**kwargs):
            nonlocal call_count
            await asyncio.sleep(0)  # yield to event loop
            call_count += 1
            return "ok"

        groq = AsyncMock()
        groq.generate_response = slow_generate
        router = LLMRouter(groq=groq)

        # Fire 50 concurrent requests
        tasks = [router.generate(f"msg-{i}") for i in range(50)]
        await asyncio.gather(*tasks)

        assert router._usage["groq"] == 50
        assert call_count == 50


class TestLLMRouterDailyReset:
    @pytest.mark.asyncio
    async def test_daily_reset_clears_counters(self):
        """Simulating a date change causes counters to reset on next call."""
        from datetime import date

        groq = _make_mock_provider("ok")
        router = LLMRouter(groq=groq)
        router._usage["groq"] = 100

        # Simulate yesterday's date
        router._usage_date = date(2000, 1, 1)

        # Next generate() call should trigger reset before routing
        await router.generate("hello")

        # After reset + 1 new call the counter is exactly 1
        assert router._usage["groq"] == 1
