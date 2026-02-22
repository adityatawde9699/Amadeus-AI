"""
LLM Request Router for Amadeus AI.

Routes requests across providers to stay within $7/month budget:
- Groq:   free tier (14,400 req/day) — PRIMARY
- Gemini: free tier (1,500 req/day)  — SECONDARY
- OpenAI: paid ($0.005/req)          — EMERGENCY for high complexity only

Usage tracking resets daily at midnight (UTC).
"""

import logging
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from src.core.exceptions import LLMRateLimitError

if TYPE_CHECKING:
    from src.infra.llm.gemini_adapter import GeminiAdapter
    from src.infra.llm.groq_adapter import GroqAdapter


logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Routes LLM requests across providers to optimize cost and availability.

    Priority order: Groq → Gemini → OpenAI (high complexity only)
    Daily counters reset automatically at UTC midnight.
    """

    DAILY_LIMITS: dict[str, int] = {
        "groq": 14400,   # Free tier — Llama 3.3 70B
        "gemini": 1500,  # Free tier — Gemini 2.5 Flash
        "openai": 100,   # Paid — $0.50/month safety buffer
    }

    # Cost per request in USD (for cost tracking)
    COST_PER_REQUEST: dict[str, float] = {
        "groq": 0.0,      # Free
        "gemini": 0.0,    # Free tier
        "openai": 0.005,  # Paid
    }

    def __init__(
        self,
        groq: "GroqAdapter | None" = None,
        gemini: "GeminiAdapter | None" = None,
        openai: object | None = None,
    ) -> None:
        self._providers: dict[str, object] = {}
        if groq:
            self._providers["groq"] = groq
        if gemini:
            self._providers["gemini"] = gemini
        if openai:
            self._providers["openai"] = openai

        self._usage: dict[str, int] = defaultdict(int)
        self._usage_date: date = date.today()

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

        providers_order = ["groq", "gemini"]
        if complexity == "high":
            providers_order.append("openai")

        for provider_name in providers_order:
            if provider_name not in self._providers:
                continue

            limit = self.DAILY_LIMITS.get(provider_name, 0)
            if self._usage[provider_name] >= limit:
                logger.warning(
                    "Provider %s at daily limit (%d). Trying next.",
                    provider_name, limit,
                )
                continue

            try:
                provider = self._providers[provider_name]
                result = await provider.generate_response(  # type: ignore[union-attr]
                    prompt=prompt,
                    context=context,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._usage[provider_name] += 1

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
                logger.error(
                    "Provider %s failed: %s. Trying next.",
                    provider_name, type(e).__name__,
                )
                continue

        raise LLMRateLimitError("All LLM providers at daily limit or unavailable")

    def get_usage_report(self) -> dict:
        """Return current usage stats and cost estimates."""
        self._reset_if_new_day()
        return {
            "date": self._usage_date.isoformat(),
            "providers_configured": list(self._providers.keys()),
            "usage": dict(self._usage),
            "limits": {
                k: v for k, v in self.DAILY_LIMITS.items()
                if k in self._providers
            },
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
            self._usage.get(provider, 0) * cost
            for provider, cost in self.COST_PER_REQUEST.items()
        )
