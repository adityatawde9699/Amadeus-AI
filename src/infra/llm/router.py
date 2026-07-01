"""
LLM Request Router for Amadeus AI.

Routing priority (local-first, complexity-aware):
- LlamaCpp: local GGUF model (offline, primary for simple/normal tasks)
- Ollama:   local server inference (offline, secondary local)
- Groq:     free cloud tier (14,400 req/day) — used for normal/high complexity
- Gemini:   free cloud tier (1,500 req/day)  — fallback cloud
- OpenAI:   paid ($0.005/req)               — emergency only

Complexity levels (auto-scored by ComplexityScorer):
  simple  (0-1) → llama_cpp/ollama only
  normal  (2-4) → llama_cpp/ollama first, cloud fallback
  high    (5+)  → skip local models, start at groq/gemini

When LOCAL_ONLY_MODE=true, only local models are used. No cloud calls.
Usage tracking resets daily at midnight (UTC).
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, ClassVar

from opentelemetry import trace

from src.core.exceptions import LLMRateLimitError
from src.runtime.events import EventBus


if TYPE_CHECKING:
    from src.core.interfaces.services import ILLMService
    from src.infra.llm.gemini_adapter import GeminiAdapter
    from src.infra.llm.groq_adapter import GroqAdapter
    from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter
from src.infra.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException


logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER HEALTH
# =============================================================================

@dataclass
class ProviderHealth:
    name: str
    p95_latency_ms: float = 1000.0
    timeout_rate: float = 0.0      # timeouts / total calls (rolling 100)
    tokens_per_second: float = 20.0
    error_rate: float = 0.0

def provider_score(h: ProviderHealth) -> float:
    return (
        (1 / max(h.p95_latency_ms, 1)) * 0.4
        + (1 - h.timeout_rate) * 0.35
        + (1 - h.error_rate) * 0.25
    )

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
        "groq": 14400,  # Free tier — Llama 3.3 70B
        "gemini": 1500,  # Free tier — Gemini 2.5 Flash
    }

    # Cost per request in USD (for cost tracking)
    COST_PER_REQUEST: ClassVar[dict[str, float]] = {
        "llama_cpp": 0.0,
        "groq": 0.0,  # Free
        "gemini": 0.0,  # Free tier
    }

    def __init__(
        self,
        llama_cpp: "LlamaCppAdapter | None" = None,
        groq: "GroqAdapter | None" = None,
        gemini: "GeminiAdapter | None" = None,
        redis_url: str | None = None,
        local_only_mode: bool = False,
        event_bus: EventBus | None = None,
    ) -> None:
        self.event_bus = event_bus
        self._providers: dict[str, ILLMService] = {}
        # LlamaCpp (SLM) is always first — locally prioritized
        if llama_cpp:
            self._providers["llama_cpp"] = llama_cpp
        if not local_only_mode:
            if groq:
                self._providers["groq"] = groq
            if gemini:
                self._providers["gemini"] = gemini

        self._local_only_mode = local_only_mode
        if local_only_mode:
            logger.info(
                "LLMRouter: LOCAL_ONLY_MODE active — cloud providers disabled, using local models only"
            )

        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        for p in self._providers:
            self._circuit_breakers[p] = CircuitBreaker(
                name=f"llm_{p}",
                failure_threshold=3,
                recovery_timeout=60,
                event_bus=self.event_bus
            )

        # In-memory counters (always present; Redis supplements these)
        self._usage: dict[str, int] = defaultdict(int)
        self._usage_date: date = date.today()
        # asyncio.Lock protects _usage from concurrent coroutine interleaving
        self._lock: asyncio.Lock = asyncio.Lock()

        # Track ProviderHealth
        self._provider_health: dict[str, ProviderHealth] = {
            p: ProviderHealth(name=p) for p in self._providers
        }
        self._call_history: dict[str, deque[tuple[float, bool]]] = {
            p: deque(maxlen=100) for p in self._providers
        }

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

    # Approximate chars-per-token for context-ceiling guard
    _CHARS_PER_TOKEN: ClassVar[float] = 4.0

    # llama_cpp context ceiling — skip local if prompt is this close to the limit
    _LLAMA_CTX_LIMIT: ClassVar[int] = 4096
    _LLAMA_CTX_SAFETY_RATIO: ClassVar[float] = 0.85  # skip when > 85% of ctx used

    async def generate(
        self,
        prompt: str,
        context: object = None,
        complexity: str = "normal",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        structured: bool = False,
    ) -> tuple[str, str]:
        """
        Generate a response using the best available provider.

        Args:
            prompt:     The user prompt.
            context:    ConversationContext (optional).
            complexity: Routing hint.
            temperature: Sampling temperature.
            max_tokens:  Max output tokens.
            structured:  True if the output MUST be valid JSON.
        """
        self._reset_if_new_day()

        # If structured is True, ensure complexity is at least 'normal'
        effective_complexity = "normal" if structured and complexity == "simple" else complexity

        # If structured is True, inject JSON instruction if not present
        if structured and "JSON" not in prompt.upper():
            prompt += "\n\nIMPORTANT: Respond ONLY with a valid JSON object."

        logger.info("LLMRouter: effective_complexity=%r structured=%r", effective_complexity, structured)

        # ── Build provider priority list ─────────────────────────────────────
        if effective_complexity == "high" and not self._local_only_mode:
            # High complexity: prioritize cloud models, local as last-resort fallback
            cloud_order = ["groq", "gemini"]
            local_order = ["llama_cpp"]
        else:
            # simple / normal / auto: LOCAL FIRST — always try Llama before cloud.
            # Health-score sort only reorders within the cloud tier.
            cloud_order = ["groq", "gemini"]
            local_order = ["llama_cpp"]

        # Respect LOCAL_ONLY_MODE
        if self._local_only_mode:
            cloud_order = []

        # Sort cloud providers by health score (best first)
        active_cloud = [p for p in cloud_order if p in self._providers]
        active_cloud.sort(
            key=lambda p: provider_score(self._provider_health[p]), reverse=True
        )
        active_local = [p for p in local_order if p in self._providers]

        # Final ordered list: local first for auto/simple/normal, cloud first for high
        if effective_complexity == "high" and not self._local_only_mode:
            active_providers = active_cloud + active_local
        else:
            active_providers = active_local + active_cloud

        for provider_name in active_providers:
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

            # ── llama_cpp context-ceiling guard ───────────────────────────────
            if provider_name == "llama_cpp":
                estimated_tokens = len(prompt) / self._CHARS_PER_TOKEN
                ceiling = self._LLAMA_CTX_LIMIT * self._LLAMA_CTX_SAFETY_RATIO
                if estimated_tokens > ceiling:
                    logger.warning(
                        "LLMRouter: prompt (~%d tokens) near llama_cpp ctx limit (%d). "
                        "Skipping local model to avoid truncation.",
                        int(estimated_tokens),
                        self._LLAMA_CTX_LIMIT,
                    )
                    continue

                # ── Skip local model for structured JSON calls ─────────────────
                # Small local models (Qwen3-2B, Llama-1B) do not reliably output
                # pure JSON — they prepend chain-of-thought prose and refuse the
                # schema.  Route structured calls directly to cloud providers.
                if structured and not self._local_only_mode:
                    logger.debug(
                        "LLMRouter: skipping llama_cpp for structured=True — "
                        "routing to cloud provider for reliable JSON output."
                    )
                    continue

            try:
                provider = self._providers[provider_name]
                cb = self._circuit_breakers[provider_name]

                tracer = trace.get_tracer(__name__)
                with tracer.start_as_current_span(f"LLMRouter.generate ({provider_name})") as span:
                    span.set_attribute("provider.name", provider_name)
                    span.set_attribute("prompt.complexity", effective_complexity)

                    t_start = time.time()
                    try:
                        result = await cb.call(
                            provider.generate_response,
                            prompt=prompt,
                            context=context,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                        success = True
                    except Exception as e:
                        span.record_exception(e)
                        success = False
                        raise
                    finally:
                        latency_ms = (time.time() - t_start) * 1000
                        span.set_attribute("provider.latency_ms", latency_ms)
                        async with self._lock:
                            history = self._call_history[provider_name]
                            history.append((latency_ms, success))
                            if history:
                                # Quick rolling average for p95 mock
                                latencies = [x[0] for x in history if x[1]]
                                if latencies:
                                    self._provider_health[provider_name].p95_latency_ms = sum(latencies)/len(latencies)
                                fails = sum(1 for x in history if not x[1])
                                self._provider_health[provider_name].error_rate = fails / len(history)

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
            except CircuitBreakerOpenException:
                logger.warning("Provider %s circuit is OPEN, trying next.", provider_name)
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

    async def warmup(self) -> None:
        """
        Eagerly initialize local providers (LlamaCpp) so the first user request
        is not blocked by model loading. Called during runtime startup.
        """
        llama = self._providers.get("llama_cpp")
        if llama is not None and hasattr(llama, "_get_llm"):
            try:
                logger.info("LLMRouter: warming up LlamaCpp model (eager load)...")
                await llama._get_llm()  # type: ignore[attr-defined]
                logger.info("LLMRouter: LlamaCpp warmup complete — model is hot.")
            except Exception as exc:
                logger.warning("LLMRouter: LlamaCpp warmup failed (will retry on first request): %s", exc)
