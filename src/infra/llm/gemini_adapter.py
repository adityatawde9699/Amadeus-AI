"""
Gemini LLM adapter implementation.

This adapter wraps the Google Generative AI library and implements
the ILLMService interface from src/core/interfaces/services.py.
"""

import hashlib
import logging
from typing import Any

from google import genai
from google.genai import types

from src.core.config import get_settings
from src.core.domain.models import (
    ConversationContext,
    ToolDefinition,
    ToolExecutionResult,
)
from src.core.exceptions import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
    MissingAPIKeyError,
)
from src.core.interfaces.services import ILLMService


logger = logging.getLogger(__name__)


class GeminiAdapter(ILLMService):
    """
    Google Gemini LLM adapter.

    Provides text generation and function calling capabilities
    using the Google Generative AI API.
    """

    def __init__(self, api_key: str | None = None, redis_client: Any = None) -> None:
        self._settings = get_settings()
        self._api_key = api_key or self._settings.GEMINI_API_KEY
        self._redis = redis_client
        self._client: genai.Client | None = None
        self._model_name = "gemini-2.5-flash"
        self._configured = False

    def _configure(self) -> None:
        """Configure the Gemini API client."""
        if self._configured:
            return

        if not self._api_key:
            raise MissingAPIKeyError("GEMINI_API_KEY")

        self._client = genai.Client(api_key=self._api_key)
        self._configured = True
        logger.info("Gemini API configured (google.genai SDK)")

    def _sanitize_input(self, text: str) -> str:
        """Sanitize user input before sending to LLM.

        Detects prompt injection patterns and logs a structured warning.
        Does NOT block — logging only, letting the LLM handle it naturally.
        This prevents secret leakage in logs while maintaining observability.
        """
        if not text:
            return ""

        # Remove null bytes (can break tokenizers)
        text = text.replace("\x00", "")

        # Remove non-printable chars but keep newlines and tabs
        text = "".join(c for c in text if c.isprintable() or c in "\n\t")

        # Limit excessive length
        max_length = self._settings.FILE_READ_MAX_CHARS or 10000
        if len(text) > max_length:
            text = text[:max_length] + "... [truncated]"

        # Prompt injection detection (log only — do NOT block)
        _INJECTION_PATTERNS = (
            "ignore previous instructions",
            "disregard your system prompt",
            "you are now a",
            "act as if you are",
            "forget everything above",
            "new instruction:",
            "system prompt:",
            "ignore all prior",
        )
        lower = text.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in lower:
                logger.warning(
                    "prompt_injection_attempt_detected",
                    extra={"pattern_prefix": pattern[:20]},
                )
                break  # Log once per input — no need to check further

        return text.strip()

    def _build_prompt_with_context(
        self,
        prompt: str,
        context: ConversationContext | None,
    ) -> str:
        """Build a prompt with conversation context."""
        prompt = self._sanitize_input(prompt)

        if not context or not context.messages:
            return prompt

        # Build context from recent messages
        history_parts = []
        for msg in context.get_recent_messages(10):
            role = "User" if msg.role == "user" else "Assistant"
            history_parts.append(f"{role}: {msg.content}")

        if history_parts:
            history = "\n".join(history_parts)
            return f"""Previous conversation:
{history}

Current user message: {prompt}"""

        return prompt

    def _get_system_prompt(self) -> str:
        """Get the system prompt for Amadeus."""
        return f"""You are {self._settings.ASSISTANT_NAME}, an AI assistant.
Personality: {self._settings.ASSISTANT_PERSONALITY}
Location context: {self._settings.DEFAULT_LOCATION}
Timezone: {self._settings.TIMEZONE}

Guidelines:
- Be helpful, accurate, and concise
- If you don't know something, say so
- For tasks, actions, or queries that require tools, use function calling
- Keep responses conversational but informative"""

    async def generate_response(
        self,
        prompt: str,
        context: ConversationContext | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a text response using Gemini."""
        self._configure()

        try:
            full_prompt = self._build_prompt_with_context(prompt, context)

            # Check cache first
            cache_key = None
            if self._redis:
                key_str = f"gemini:response:{full_prompt}:{temperature}:{max_tokens}"
                cache_key = hashlib.md5(key_str.encode(), usedforsecurity=False).hexdigest()  # nosec B324
                cached = await self._redis.get(cache_key)
                if cached:
                    logger.debug("Cache hit for Gemini response")
                    return str(cached)

            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens or 1024,
                system_instruction=self._get_system_prompt(),
            )

            assert self._client is not None  # set by _configure()
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=full_prompt,
                config=config,
            )

            if not response.text:
                raise LLMResponseError("Empty response from Gemini")

            # Store in cache (expire after 24h)
            if self._redis and cache_key:
                await self._redis.setex(cache_key, 86400, response.text)

            return str(response.text)

        except Exception as e:
            error_str = str(e).lower()
            if "block" in error_str or "safety" in error_str:
                logger.warning(f"Prompt blocked: {e}")
                raise LLMResponseError("Content was blocked by safety filters")
            if "429" in error_str or "rate" in error_str:
                raise LLMRateLimitError("Gemini", retry_after=60)
            if "connection" in error_str or "network" in error_str:
                raise LLMConnectionError("Gemini", str(e))
            logger.exception(f"Gemini error: {e}")
            raise LLMResponseError(str(e))

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        context: ConversationContext | None = None,
    ) -> tuple[str | None, ToolExecutionResult | None]:
        """Generate response with function calling capability."""
        self._configure()

        try:
            # Convert tool definitions to Gemini function declarations
            gemini_tools = self._convert_tools(tools)

            full_prompt = self._build_prompt_with_context(prompt, context)

            # Function calls are extremely dynamic so simple string caching
            # might not be safe unless context is identical and simple.
            # For this exercise, caching is mostly effective on direct interactions.
            cache_key = None
            if self._redis and not tools:
                key_str = f"gemini:tools:{full_prompt}"
                cache_key = hashlib.md5(key_str.encode(), usedforsecurity=False).hexdigest()  # nosec B324
                cached = await self._redis.get(cache_key)
                if cached:
                    logger.debug("Cache hit for Gemini tool response")
                    return cached, None

            config = types.GenerateContentConfig(
                system_instruction=self._get_system_prompt(),
                tools=gemini_tools if gemini_tools else None,
            )

            assert self._client is not None  # set by _configure()
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=full_prompt,
                config=config,
            )

            # Check if the model wants to call a function
            if response.function_calls:
                fc = response.function_calls[0]
                return None, ToolExecutionResult(
                    tool_name=fc.name or "unknown",
                    success=True,
                    result={"args": dict(fc.args) if fc.args else {}},
                )

            # No function call, return text response
            return response.text, None

        except Exception as e:
            logger.exception(f"Gemini function calling error: {e}")
            # Fall back to text-only response
            text = await self.generate_response(prompt, context)
            return text, None

    def _convert_tools(self, tools: list[ToolDefinition]) -> list:
        """Convert tool definitions to Gemini format."""
        if not tools:
            return []

        gemini_tools = []
        for tool in tools:
            # Convert parameters to Gemini schema format
            properties = {}
            required = []

            for param_name, param_info in tool.parameters.items():
                if isinstance(param_info, dict):
                    properties[param_name] = {
                        "type": param_info.get("type", "string"),
                        "description": param_info.get("description", ""),
                    }
                    if param_info.get("required", False):
                        required.append(param_name)
                else:
                    properties[param_name] = {"type": "string"}

            gemini_tools.append({
                "function_declarations": [{
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }]
            })

        return gemini_tools
