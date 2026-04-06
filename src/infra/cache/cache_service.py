"""
Unified Redis Cache Service for Amadeus AI.

Provides namespaced caching for LLM responses, TTS audio, tool results,
and search results. Each namespace has an appropriate TTL.

Cache namespaces and TTLs:
- llm:    3600s  (1 hour)  — LLM responses (may become stale)
- tts:    86400s (24 hours) — Audio for common phrases
- tool:   300s   (5 min)   — Weather, news, system stats
- search: 1800s  (30 min)  — Search results

Usage:
    cache = CacheService(redis_client)
    cached = await cache.get_llm(prompt)
    if not cached:
        response = await llm.generate(prompt)
        await cache.set_llm(prompt, response)
"""

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from redis.asyncio import Redis


logger = logging.getLogger(__name__)


# Tools whose results are safe to cache (stateless, non-mutating)
CACHEABLE_TOOLS: frozenset[str] = frozenset({
    "get_weather",
    "get_news",
    "get_datetime_info",
    "wikipedia_search",
    "web_search",
    "get_cpu_usage",
    "get_memory_info",
    "get_battery_info",
    "system_status",
    "tell_joke",
})


class CacheService:
    """
    Unified cache for Amadeus AI services.

    If a Redis client is provided, it acts as a distributed Redis cache.
    If Redis is unavailable (Local Zero-Dependency Mode), it falls back seamlessly
    to a thread-safe in-memory dictionary cache.
    """

    NAMESPACES: dict[str, int] = {
        "llm": 3600,     # 1 hour
        "tts": 86400,    # 24 hours
        "tool": 300,     # 5 minutes
        "search": 1800,  # 30 minutes
    }

    def __init__(self, redis: "Redis | None" = None) -> None:
        self._redis = redis
        self._hits = 0
        self._misses = 0

        # In-Memory Fallback Cache: dict[key, tuple[expiry_timestamp, value]]
        self._local_cache: dict[str, tuple[float, Any]] = {}

    def _key(self, namespace: str, content: str) -> str:
        """Generate a namespaced key using a SHA-256 hash of content."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"amadeus:{namespace}:{content_hash}"

    # -------------------------------------------------------------------------
    # Core Cache Implementation (Routing between Redis and Local)
    # -------------------------------------------------------------------------

    async def _get(self, key: str) -> Any | None:
        if self._redis:
            try:
                result = await self._redis.get(key)
                if result:
                    self._hits += 1
                    return result
                self._misses += 1
                return None
            except Exception as e:
                logger.debug("Redis cache GET failed: %s. Falling back to miss.", type(e).__name__)
                self._misses += 1
                return None
        else:
            # Local Cache Logic
            import time
            if key in self._local_cache:
                expiry, value = self._local_cache[key]
                if time.time() < expiry:
                    self._hits += 1
                    return value
                # Evict expired key
                del self._local_cache[key]
            self._misses += 1
            return None

    async def _set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self._redis:
            try:
                await self._redis.setex(key, ttl_seconds, value)
            except Exception as e:
                logger.debug("Redis cache SET failed: %s", type(e).__name__)
        else:
            # Local Cache Logic
            import time
            expiry = time.time() + ttl_seconds
            self._local_cache[key] = (expiry, value)

    # -------------------------------------------------------------------------
    # LLM Response Cache
    # -------------------------------------------------------------------------

    async def get_llm(self, prompt: str, provider: str = "") -> str | None:
        """Retrieve cached LLM response for a prompt."""
        key = self._key("llm", f"{provider}:{prompt}")
        result = await self._get(key)
        if result is not None:
             return result.decode() if isinstance(result, bytes) else result
        return None

    async def set_llm(self, prompt: str, response: str, provider: str = "") -> None:
        """Cache an LLM response."""
        key = self._key("llm", f"{provider}:{prompt}")
        await self._set(key, response, self.NAMESPACES["llm"])

    # -------------------------------------------------------------------------
    # TTS Audio Cache
    # -------------------------------------------------------------------------

    async def get_tts(self, text: str, voice: str) -> bytes | None:
        """Retrieve cached TTS audio bytes."""
        key = self._key("tts", f"{voice}:{text}")
        return await self._get(key)

    async def set_tts(self, text: str, voice: str, audio: bytes) -> None:
        """Cache TTS audio bytes."""
        if not audio:
            return
        key = self._key("tts", f"{voice}:{text}")
        await self._set(key, audio, self.NAMESPACES["tts"])

    # -------------------------------------------------------------------------
    # Tool Result Cache
    # -------------------------------------------------------------------------

    async def get_tool_result(self, tool_name: str, args: dict) -> str | None:
        """Retrieve cached tool execution result."""
        if tool_name not in CACHEABLE_TOOLS:
            return None
        key = self._key("tool", f"{tool_name}:{json.dumps(args, sort_keys=True)}")
        result = await self._get(key)
        if result is not None:
            return result.decode() if isinstance(result, bytes) else result
        return None

    async def set_tool_result(self, tool_name: str, args: dict, result: str) -> None:
        """Cache a tool result (only for safe, stateless tools)."""
        if tool_name not in CACHEABLE_TOOLS:
            return
        key = self._key("tool", f"{tool_name}:{json.dumps(args, sort_keys=True)}")
        await self._set(key, result, self.NAMESPACES["tool"])

    # -------------------------------------------------------------------------
    # Search Result Cache
    # -------------------------------------------------------------------------

    async def get_search(self, query: str) -> str | None:
        """Retrieve cached search results."""
        key = self._key("search", query)
        result = await self._get(key)
        if result is not None:
            return result.decode() if isinstance(result, bytes) else result
        return None

    async def set_search(self, query: str, result: str) -> None:
        """Cache search results."""
        key = self._key("search", query)
        await self._set(key, result, self.NAMESPACES["search"])

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return cache hit/miss statistics."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate_pct": round(hit_rate, 2),
            "backend": "redis" if self._redis else "local_memory"
        }
