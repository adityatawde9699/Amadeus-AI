"""
LLM Request Router for Amadeus AI.

Routing priority (local-first):
- Ollama: unlimited local inference (phi3:mini default) — PRIMARY (free, offline)
- Groq:   free tier (14,400 req/day)                  — SECONDARY
- Gemini: free tier (1,500 req/day)                   — TERTIARY
- OpenAI: paid ($0.005/req)                           — EMERGENCY

When LOCAL_ONLY_MODE=true, only Ollama is used. No cloud calls.
Usage tracking resets daily at midnight (UTC).
"""

import asyncio
import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar

from src.core.exceptions import LLMRateLimitError


if TYPE_CHECKING:
    from src.infra.llm.gemini_adapter import GeminiAdapter
    from src.infra.llm.groq_adapter import GroqAdapter
    from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter
    from src.infra.llm.ollama_adapter import OllamaAdapter


logger = logging.getLogger(__name__)


# =============================================================================
# REDIS COUNTER BACKEND
# =============================================================================


class _RedisCounterBackend:
    """
    Redis-backed daily usage counters for multi-worker LLMRouter deployments.

    Key pattern: ``llm_usage:{provider}:{YYYY-MM-DD}``
    TTL: 86400 seconds (auto-expiry at end of day).

    Falls back gracefully to None so callers can use in-memory fallback.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any | None = None

    async def _get_client(self) -> Any | None:
        """Get or create redis client, returns None on failure."""
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self._redis_url, decode_responses=True)
            # Verify connectivity
            await client.ping()  # type: ignore[misc]
            self._client = client
            logger.info("LLMRouter connected to Redis for shared quota tracking")
        except Exception as e:
            logger.warning(
                "Redis unavailable for LLM quota tracking (%s) — using in-memory fallback",
                type(e).__name__,
            )
            self._client = None
        return self._client

    def _key(self, provider: str) -> str:
        return f"llm_usage:{provider}:{date.today().isoformat()}"

    async def get(self, provider: str) -> int:
        """Return today's usage count for a provider (0 if Redis unavailable)."""
        client = await self._get_client()
        if client is None:
            return 0
        try:
            val = await client.get(self._key(provider))
            return int(val) if val else 0
        except Exception:
            return 0

    async def increment(self, provider: str) -> None:
        """Atomically increment and set TTL for a provider's daily counter."""
        client = await self._get_client()
        if client is None:
            return
        try:
            key = self._key(provider)
            pipe = client.pipeline()
            await pipe.incr(key)
            await pipe.expire(key, 86400)
            await pipe.execute()
        except Exception as e:
            logger.debug("Redis increment failed: %s", e)


class LLMRouter:
    """
    Routes LLM requests across providers to optimize cost and availability.

    Priority order (local-first):
      1. LlamaCpp  — local GGUF model via llama-cpp-python (offline, primary)
      2. Ollama    — local server inference (offline, secondary)
      3. Groq      — free cloud tier (14,400 req/day)
      4. Gemini    — free cloud tier (1,500 req/day)
      5. OpenAI    — paid, only for high-complexity requests

    Daily counters reset automatically at UTC midnight.
    When LOCAL_ONLY_MODE=True, steps 3-5 are skipped entirely.
    """

    DAILY_LIMITS: ClassVar[dict[str, int]] = {
        "llama_cpp": 999_999,  # Local SLM — unlimited
        "ollama": 999_999,  # Local — effectively unlimited
        "groq": 14400,  # Free tier — Llama 3.3 70B
        "gemini": 1500,  # Free tier — Gemini 2.5 Flash
        "openai": 100,  # Paid — $0.50/month safety buffer
    }

    # Cost per request in USD (for cost tracking)
    COST_PER_REQUEST: ClassVar[dict[str, float]] = {
        "llama_cpp": 0.0,
        "ollama": 0.0,  # Free — runs locally on your machine
        "groq": 0.0,  # Free
        "gemini": 0.0,  # Free tier
        "openai": 0.005,  # Paid
    }

    def __init__(
        self,
        ollama: "OllamaAdapter | None" = None,
        llama_cpp: "LlamaCppAdapter | None" = None,
        groq: "GroqAdapter | None" = None,
        gemini: "GeminiAdapter | None" = None,
        openai: object | None = None,
        redis_url: str | None = None,
        local_only_mode: bool = False,
    ) -> None:
        self._providers: dict[str, object] = {}
        # LlamaCpp (SLM) is always first — locally prioritized
        if llama_cpp:
            self._providers["llama_cpp"] = llama_cpp
        # Ollama is secondary local option
        if ollama:
            self._providers["ollama"] = ollama
        if not local_only_mode:
            if groq:
                self._providers["groq"] = groq
            if gemini:
                self._providers["gemini"] = gemini
            if openai:
                self._providers["openai"] = openai

        self._local_only_mode = local_only_mode
        if local_only_mode:
            logger.info("LLMRouter: LOCAL_ONLY_MODE active — cloud providers disabled, using local models only")

        # In-memory counters (always present; Redis supplements these)
        self._usage: dict[str, int] = defaultdict(int)
        self._usage_date: date = date.today()
        # asyncio.Lock protects _usage from concurrent coroutine interleaving
        self._lock: asyncio.Lock = asyncio.Lock()

        # Redis backend for shared quota tracking across multiple workers
        self._redis: _RedisCounterBackend | None = (
            _RedisCounterBackend(redis_url) if redis_url else None
        )

    def _reset_if_new_day(self) -> None:
        """Reset daily counters if the date has changed."""
        today = date.today()
        if today != self._usage_date:
            logger.info(
                "Daily LLM usage reset. Previous day totals: %s",
                dict(self._usage),
            )
            self._usage.clear()
            self._usage_date = today

    async def generate(
        self,
        prompt: str,
        context: object = None,
        complexity: str = "normal",
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, str]:
        """
        Generate a response using the best available provider.

        Args:
            prompt: The user prompt
            context: ConversationContext (optional)
            complexity: "normal" or "high" — high enables OpenAI as last resort
            temperature: Generation temperature
            max_tokens: Max output tokens

        Returns:
            Tuple of (response_text, provider_name_used)

        Raises:
            LLMRateLimitError: All providers at daily limit
        """
        self._reset_if_new_day()

        # Build provider priority: LlamaCpp first, then Ollama (both local), then cloud
        providers_order = ["llama_cpp", "ollama", "groq", "gemini"]
        if complexity == "high" and not self._local_only_mode:
            providers_order.append("openai")

        for provider_name in providers_order:
            if provider_name not in self._providers:
                continue

            limit = self.DAILY_LIMITS.get(provider_name, 0)

            # Use Redis count when available; in-memory otherwise
            if self._redis:
                redis_count = await self._redis.get(provider_name)
                current_usage = max(self._usage[provider_name], redis_count)
            else:
                current_usage = self._usage[provider_name]

            if current_usage >= limit:
                logger.warning(
                    "Provider %s at daily limit (%d). Trying next.",
                    provider_name,
                    limit,
                )
                continue

            try:
                provider = self._providers[provider_name]
                result = await provider.generate_response(  # type: ignore[attr-defined]
                    prompt=prompt,
                    context=context,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                async with self._lock:
                    self._usage[provider_name] += 1
                # Persist to Redis so other workers see the updated count
                if self._redis:
                    await self._redis.increment(provider_name)

                logger.debug(
                    "LLM request routed to %s (daily: %d/%d)",
                    provider_name,
                    self._usage[provider_name],
                    limit,
                )

                # Alert if daily cost is getting high
                daily_cost = self._calculate_cost()
                if daily_cost > 0.25:
                    logger.warning(
                        "Daily LLM cost alert: $%.4f exceeds $0.25 threshold",
                        daily_cost,
                    )

                return result, provider_name

            except LLMRateLimitError:
                logger.warning("Provider %s rate limited, trying next.", provider_name)
                continue
            except Exception as e:
                logger.exception(
                    "Provider %s failed: %s. Trying next.",
                    provider_name,
                    type(e).__name__,
                )
                continue

        raise LLMRateLimitError("all_providers", retry_after=None)

    def get_usage_report(self) -> dict:
        """Return current usage stats and cost estimates."""
        self._reset_if_new_day()
        return {
            "date": self._usage_date.isoformat(),
            "providers_configured": list(self._providers.keys()),
            "usage": dict(self._usage),
            "limits": {k: v for k, v in self.DAILY_LIMITS.items() if k in self._providers},
            "remaining": {
                k: max(0, self.DAILY_LIMITS.get(k, 0) - self._usage.get(k, 0))
                for k in self._providers
            },
            "estimated_cost_usd": round(self._calculate_cost(), 6),
            "budget_remaining_usd": round(max(0.0, 0.25 - self._calculate_cost()), 6),
        }

    def _calculate_cost(self) -> float:
        """Calculate estimated cost for today's usage."""
        return sum(
            self._usage.get(provider, 0) * cost for provider, cost in self.COST_PER_REQUEST.items()
        )
