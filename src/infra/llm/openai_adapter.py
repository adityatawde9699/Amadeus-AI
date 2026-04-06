"""
OpenAI LLM Adapter for Amadeus AI.

Emergency fallback provider — only used when both Groq and Gemini are
exhausted or unavailable.  Keeps costs at zero under normal operation.

GPT-4o-mini is the default model (cheapest capable option).
Supports native OpenAI function-calling via generate_with_tools().
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


class OpenAIAdapter(ILLMService):
    """
    OpenAI LLM adapter — emergency fallback (paid, use sparingly).

    Default model: gpt-4o-mini (cheapest capable option).
    Supports native function-calling via the tools/tool_choice API.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._settings = get_settings()
        self._api_key = api_key or self._settings.OPENAI_API_KEY
        self._client: Any = None
        self._configured = False

    def _configure(self) -> None:
        """Lazy-initialize the async OpenAI client."""
        if self._configured:
            return

        if not self._api_key:
            raise MissingAPIKeyError("OPENAI_API_KEY")

        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self._api_key)
            self._configured = True
            model = getattr(self._settings, "OPENAI_MODEL", "gpt-4o-mini")
            logger.info("OpenAI adapter configured with model %s", model)
        except ImportError as e:
            raise LLMConnectionError(
                "OpenAI", "openai package not installed. Run: pip install openai"
            ) from e

    def _get_system_prompt(self) -> str:
        """Build the system prompt for Amadeus."""
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
        """Generate a text response using the OpenAI Chat Completions API."""
        self._configure()

        model = getattr(self._settings, "OPENAI_MODEL", "gpt-4o-mini")
        messages = self._build_messages(prompt, context)

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or 1024,
            )
            result = response.choices[0].message.content or ""
            if not result:
                raise LLMResponseError("Empty response from OpenAI")
            return result

        except LLMResponseError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate_limit" in error_str or "rate limit" in error_str:
                raise LLMRateLimitError("OpenAI", retry_after=60)
            if (
                "connection" in error_str
                or "network" in error_str
                or "timeout" in error_str
            ):
                raise LLMConnectionError("OpenAI", str(e))
            logger.exception("OpenAI error: %s", type(e).__name__)
            raise LLMResponseError(str(e)) from e

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        context: ConversationContext | None = None,
    ) -> tuple[str | None, ToolExecutionResult | None]:
        """
        Generate a response with native OpenAI function-calling.

        Converts Amadeus ToolDefinition objects to the OpenAI tools format,
        then parses the model's tool_call response back to ToolExecutionResult.
        """
        self._configure()

        model = getattr(self._settings, "OPENAI_MODEL", "gpt-4o-mini")
        messages = self._build_messages(prompt, context)

        # Convert ToolDefinition → OpenAI function schema
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                },
            })

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools if openai_tools else None,
                tool_choice="auto" if openai_tools else None,
            )
            choice = response.choices[0]
            msg = choice.message

            # If the model called a tool
            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                import json
                tc = msg.tool_calls[0]
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                tool_result = ToolExecutionResult(
                    tool_name=tool_name,
                    success=True,
                    result=args,
                )
                return None, tool_result

            # Plain text response
            text = msg.content or ""
            return text, None

        except LLMRateLimitError:
            raise
        except LLMConnectionError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate_limit" in error_str:
                raise LLMRateLimitError("OpenAI", retry_after=60)
            logger.exception("OpenAI tool-call error: %s", type(e).__name__)
            raise LLMResponseError(str(e)) from e
