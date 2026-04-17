"""
LLM Adapter Interface for Amadeus AI.

All LLM provider adapters (Ollama, LlamaCpp, Groq, Gemini, OpenAI) must
conform to this interface. The LLMRouter uses duck-typing today but this
Protocol provides static type-checking enforcement via mypy.

Usage:
    from src.core.interfaces.llm import LLMAdapter

    class MyAdapter(LLMAdapter):
        async def is_available(self) -> bool: ...
        async def generate_response(self, prompt, context, temperature, max_tokens) -> str: ...
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.core.domain.models import ConversationContext


class LLMAdapter(ABC):
    """
    Abstract base class for all LLM provider adapters.

    Every adapter registered with LLMRouter must implement this interface.
    This enforces a consistent API surface and enables static type analysis.

    Implementing classes:
        - OllamaAdapter      (local server, offline)
        - LlamaCppAdapter    (local GGUF file, offline)
        - GroqAdapter        (cloud, free tier)
        - GeminiAdapter      (cloud, free tier)
        - OpenAIAdapter      (cloud, paid)
    """

    # =========================================================================
    # REQUIRED METHODS
    # =========================================================================

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check whether this provider is currently available.

        For local adapters: verify model file/server exists.
        For cloud adapters: can return True immediately (quota is tracked by router).

        Returns:
            True if the adapter can accept generation requests right now.
        """

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: "ConversationContext | None" = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a complete response for the given prompt.

        Args:
            prompt:      The current user message / formatted prompt string.
            context:     Optional ConversationContext carrying message history.
                         Adapters should inject history into the messages list
                         so the model has multi-turn awareness.
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
            max_tokens:  Maximum tokens to generate. None means use adapter default.

        Returns:
            The generated text string (stripped of leading/trailing whitespace).

        Raises:
            ConfigurationError:  Provider is misconfigured (missing key/path).
            LLMConnectionError:  Could not connect to / initialize the provider.
            LLMResponseError:    Generation succeeded at transport layer but
                                 the response was empty or malformed.
            LLMRateLimitError:   Provider daily quota has been reached.
        """

    # =========================================================================
    # OPTIONAL METHODS
    # =========================================================================

    async def stream_response(
        self,
        prompt: str,
        context: "ConversationContext | None" = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens one-by-one (optional — not all adapters support it).

        Default implementation calls generate_response() and yields the full
        text as a single chunk, so adapters that don't support true streaming
        still work correctly in streaming contexts.

        Args:
            prompt:      The current user message.
            context:     Optional ConversationContext.
            temperature: Sampling temperature.
            max_tokens:  Maximum tokens to generate.

        Yields:
            Individual token / chunk strings as they are produced.
        """
        response = await self.generate_response(
            prompt=prompt,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield response

    def get_provider_name(self) -> str:
        """
        Human-readable provider identifier used in logs and usage reports.

        Override in subclasses for a cleaner name (e.g. "Groq", "Ollama").
        Default falls back to the class name.
        """
        return type(self).__name__

    def get_capabilities(self) -> dict[str, Any]:
        """
        Return a dict describing what this adapter supports.

        Useful for the /api/v1/llm/status endpoint and UI feature flags.

        Returns:
            Dict with keys like 'streaming', 'function_calling', 'vision', etc.
        """
        return {
            "streaming": False,
            "function_calling": False,
            "vision": False,
            "local": False,
        }
