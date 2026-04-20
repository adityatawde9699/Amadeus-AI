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
import re
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
# COMPLEXITY SCORER
# =============================================================================


class ComplexityScorer:
    """
    Pure heuristic scorer that estimates how complex a prompt is so the
    LLMRouter can decide whether to use the local model or escalate to cloud.

    Scoring rubric (additive):
      +3  Very long prompt  (>300 whitespace-split tokens)
      +3  Multi-step indicator ("and then", "step by step", "after that", ...)
      +2  Code / programming keywords
      +2  Creative writing request
      +2  Math / formal reasoning / proof request
      +2  Long summarisation task and/or very long input (>500 chars)
      +1  Abstract / philosophical question
      +1  Multiple questions in one input (≥2 question marks)

    Thresholds:
      0-1  → "simple"  — local model is perfectly capable
      2-3  → "normal"  — local first, cloud fallback on failure
      4+   → "high"    — skip local, go straight to Groq/Gemini
    """

    # ── keyword sets ──────────────────────────────────────────────────────────
    _MULTI_STEP = re.compile(
        r"\band then\b|\bafter that\b|\bstep by step\b|\bfirst.*then\b"
        r"|\bsequentially\b|\bone by one\b|\bfinally\b.*\bfirst\b",
        re.IGNORECASE,
    )
    # Code: (action verb) ... (code noun) OR bare language name OR literals
    # re.DOTALL so multi-line prompts still match.
    _CODE = re.compile(
        r"\b(write|create|generate|implement|build|debug|fix|refactor|optimize)\b"
        r".*?\b(code|script|function|class|program|algorithm|snippet|api|endpoint|module)\b"
        r"|\b(python|javascript|typescript|java|c\+\+|rust|sql|bash|powershell)\b"
        r"|\bdebug\s+this\b"
        r"|```|\bdef \b|\bclass \b|\bimport \b|#include",
        re.IGNORECASE | re.DOTALL,
    )
    _CREATIVE = re.compile(
        r"\b(write|compose|create|generate|draft)\b.*?"
        r"\b(story|poem|essay|blog|article|letter|song|lyric|script|novel)\b",
        re.IGNORECASE | re.DOTALL,
    )
    # Math: proof keywords OR comparison OR numerical reasoning
    _MATH = re.compile(
        r"\b(prove\s+that|proof\s+that|prove|proof|derive|calculate|compute"
        r"|solve|integrate|differentiate|is\s+irrational|is\s+rational"
        r"|eigenvalue|matrix|probability|statistics|theorem|lemma|corollary"
        r"|formal\s+proof)\b"
        r"|\bcompare\b.*?\bvs\.?\b",
        re.IGNORECASE | re.DOTALL,
    )
    _SUMMARISE = re.compile(
        r"\b(summarize|summarise|tldr|key points|main points|overview|abstract"
        r"|brief.*?from|condense|distil)\b",
        re.IGNORECASE,
    )
    # Abstract: philosophical / ethics / policy / implications
    _ABSTRACT = re.compile(
        r"\b(why does|meaning of|explain.*?concept|philosophy|ethics|moral"
        r"|implications of|implication of|impact of.*?on|effect of.*?on"
        r"|theory of|nature of|geopolitical|policy implications"
        r"|food security|climate change.*?(impact|effect|implications))\b",
        re.IGNORECASE | re.DOTALL,
    )

    def score(self, prompt: str) -> tuple[str, int]:
        """
        Score a prompt and return (level, raw_score).

        Args:
            prompt: The full prompt string sent to the LLM.

        Returns:
            Tuple of (level, score) where level is 'simple', 'normal', or 'high'.
        """
        s = 0
        tokens = prompt.split()

        # +3: Very long prompt — likely has rich context that needs a big model
        if len(tokens) > 300:
            s += 3
        # +3: Multi-step instruction — requires sequential reasoning
        if self._MULTI_STEP.search(prompt):
            s += 3
        # +4: Code / programming task — small models hallucinate APIs & syntax
        if self._CODE.search(prompt):
            s += 4
        # +4: Creative writing — small models lack stylistic depth
        if self._CREATIVE.search(prompt):
            s += 4
        # +4: Math / formal reasoning — small models make arithmetic/logic errors
        if self._MATH.search(prompt):
            s += 4
        # +2: Summarisation or long input — needs solid comprehension
        if self._SUMMARISE.search(prompt) or len(prompt) > 500:
            s += 4
        # +4: Abstract / ethical / policy topic — nuance requires a large model
        if self._ABSTRACT.search(prompt):
            s += 4
        # +1: Multiple questions — mild indicator of complexity
        if prompt.count("?") >= 2:
            s += 1

        if s <= 1:
            level = "simple"
        elif s <= 3:  # normal: 2-3
            level = "normal"
        else:  # high: 4+  (any code/creative/math hit lands here)
            level = "high"

        logger.debug(
            "ComplexityScorer: score=%d level=%r prompt_tokens=%d",
            s,
            level,
            len(tokens),
        )
        return level, s

    @staticmethod
    def merge(auto_level: str, caller_level: str) -> str:
        """
        Return the higher of auto_level and caller_level.
        Order: simple < normal < high.
        """
        _rank = {"simple": 0, "normal": 1, "high": 2}
        if _rank.get(auto_level, 0) >= _rank.get(caller_level, 1):
            return auto_level
        return caller_level


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
            logger.info(
                "LLMRouter: LOCAL_ONLY_MODE active — cloud providers disabled, using local models only"
            )

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

    # Shared scorer instance (stateless, safe to reuse)
    _scorer: ClassVar[ComplexityScorer] = ComplexityScorer()

    # Approximate chars-per-token for context-ceiling guard
    _CHARS_PER_TOKEN: ClassVar[float] = 4.0

    # llama_cpp context ceiling — skip local if prompt is this close to the limit
    _LLAMA_CTX_LIMIT: ClassVar[int] = 4096
    _LLAMA_CTX_SAFETY_RATIO: ClassVar[float] = 0.85  # skip when > 85% of ctx used

    async def generate(
        self,
        prompt: str,
        context: object = None,
        complexity: str = "auto",
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> tuple[str, str]:
        """
        Generate a response using the best available provider.

        Args:
            prompt:     The user prompt.
            context:    ConversationContext (optional).
            complexity: Routing hint — one of:
                        ``"auto"``   Score the prompt and choose the best tier.
                        ``"simple"`` Force local-only (llama_cpp / ollama).
                        ``"normal"`` Local first, cloud fallback (default).
                        ``"high"``   Skip local models, use cloud directly.
            temperature: Sampling temperature (0 = deterministic, 1 = creative).
            max_tokens:  Max output tokens.

        Returns:
            Tuple of (response_text, provider_name_used)

        Raises:
            LLMRateLimitError: All providers at or beyond their daily limit.
        """
        self._reset_if_new_day()

        # ── Complexity resolution ────────────────────────────────────────────
        if complexity == "auto":
            auto_level, auto_score = self._scorer.score(prompt)
            effective_complexity = auto_level
            logger.info(
                "LLMRouter auto-complexity: score=%d level=%r",
                auto_score,
                effective_complexity,
            )
        else:
            # Caller supplied explicit level — still run scorer so we can
            # *upgrade* (never downgrade) based on what we detect in the prompt.
            auto_level, auto_score = self._scorer.score(prompt)
            effective_complexity = ComplexityScorer.merge(auto_level, complexity)
            if effective_complexity != complexity:
                logger.info(
                    "LLMRouter upgraded complexity %r → %r (auto_score=%d)",
                    complexity,
                    effective_complexity,
                    auto_score,
                )

        # ── Build provider priority list ─────────────────────────────────────
        if effective_complexity == "high" and not self._local_only_mode:
            # High complexity: prioritize cloud models, but keep local as last-resort fallback
            providers_order = ["groq", "gemini", "openai", "llama_cpp", "ollama"]
            logger.info("LLMRouter: high complexity → prioritizing cloud with local fallback: %s", providers_order)
        else:
            # simple / normal: local first, cloud as fallback
            providers_order = ["llama_cpp", "ollama", "groq", "gemini"]
            if not self._local_only_mode and effective_complexity != "simple":
                providers_order.append("openai")

        # Respect LOCAL_ONLY_MODE
        if self._local_only_mode:
            providers_order = [p for p in providers_order if p in ("llama_cpp", "ollama")]

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
