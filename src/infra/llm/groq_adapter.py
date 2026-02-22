"""
Groq LLM Adapter for Amadeus AI.

Primary LLM provider — free tier: 14,400 requests/day.
Uses llama-3.3-70b-versatile which outperforms GPT-4 on many benchmarks.
"""

import logging
from typing import Any

from src.core.config import get_settings
from src.core.domain.models import ConversationContext, ToolDefinition, ToolExecutionResult
from src.core.exceptions import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
    MissingAPIKeyError,
)
from src.core.interfaces.services import ILLMService


logger = logging.getLogger(__name__)


class GroqAdapter(ILLMService):
    """
    Groq LLM adapter — primary provider for cost optimization.

    Groq free tier: 14,400 requests/day on llama-3.3-70b-versatile.
    No tool calling support in Groq chat API — falls back to text parsing.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._settings = get_settings()
        self._api_key = api_key or self._settings.GROQ_API_KEY
        self._client: Any = None
        self._configured = False

    def _configure(self) -> None:
        """Lazy-initialize Groq client."""
        if self._configured:
            return

        if not self._api_key:
            raise MissingAPIKeyError("GROQ_API_KEY")

        try:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
            self._configured = True
            logger.info("Groq API configured with model %s", self._settings.GROQ_MODEL)
        except ImportError as e:
            raise LLMConnectionError("Groq", "groq package not installed. Run: pip install groq") from e

    def _get_system_prompt(self) -> str:
        """Get the system prompt for Amadeus."""
        return (
            f"You are {self._settings.ASSISTANT_NAME}, an AI assistant.\n"
            f"Personality: {self._settings.ASSISTANT_PERSONALITY}\n"
            f"Location context: {self._settings.DEFAULT_LOCATION}\n"
            f"Timezone: {self._settings.TIMEZONE}\n\n"
            "Guidelines:\n"
            "- Be helpful, accurate, and concise\n"
            "- If you don't know something, say so\n"
            "- Keep responses conversational but informative"
        )

    def _build_messages(
        self,
        prompt: str,
        context: ConversationContext | None,
    ) -> list[dict[str, str]]:
        """Build message array with conversation history."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._get_system_prompt()},
        ]

        # Add recent conversation history
        if context and context.messages:
            for msg in context.get_recent_messages(8):
                role = "user" if msg.role == "user" else "assistant"
                messages.append({"role": role, "content": msg.content})

        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate_response(
        self,
        prompt: str,
        context: ConversationContext | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a text response using Groq Llama."""
        self._configure()

        try:
            import asyncio

            messages = self._build_messages(prompt, context)

            def _call_groq() -> str:
                response = self._client.chat.completions.create(
                    model=self._settings.GROQ_MODEL,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens or 1024,
                )
                return response.choices[0].message.content or ""

            # Run blocking Groq call in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _call_groq)

            if not result:
                raise LLMResponseError("Empty response from Groq")

            return result

        except LLMResponseError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                raise LLMRateLimitError("Groq", retry_after=60)
            if "connection" in error_str or "network" in error_str:
                raise LLMConnectionError("Groq", str(e))
            logger.error("Groq error: %s", type(e).__name__)
            raise LLMResponseError(str(e)) from e

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        context: ConversationContext | None = None,
    ) -> tuple[str | None, ToolExecutionResult | None]:
        """
        Generate response — Groq doesn't support native function calling yet.

        Falls back to pure text generation. The caller (AmadeusService)
        handles tool dispatch via the ML classifier instead.
        """
        text = await self.generate_response(prompt, context)
        return text, None
