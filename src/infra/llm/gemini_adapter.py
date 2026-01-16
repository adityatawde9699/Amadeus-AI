"""
Gemini LLM adapter implementation.

This adapter wraps the Google Generative AI library and implements
the ILLMService interface from src/core/interfaces/services.py.
"""

import json
import logging
from typing import Any

import google.generativeai as genai

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
    
    def __init__(self, api_key: str | None = None):
        self._settings = get_settings()
        self._api_key = api_key or self._settings.GEMINI_API_KEY
        self._model = None
        self._configured = False
    
    def _configure(self) -> None:
        """Configure the Gemini API client."""
        if self._configured:
            return
        
        if not self._api_key:
            raise MissingAPIKeyError("GEMINI_API_KEY")
        
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel("gemini-2.5-flash")
        self._configured = True
        logger.info("Gemini API configured")
    
    def _build_prompt_with_context(
        self,
        prompt: str,
        context: ConversationContext | None,
    ) -> str:
        """Build a prompt with conversation context."""
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
            
            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens or 1024,
            )
            
            response = self._model.generate_content(
                [self._get_system_prompt(), full_prompt],
                generation_config=generation_config,
            )
            
            if not response.text:
                raise LLMResponseError("Empty response from Gemini")
            
            return response.text
            
        except genai.types.BlockedPromptException as e:
            logger.warning(f"Prompt blocked: {e}")
            raise LLMResponseError("Content was blocked by safety filters")
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                raise LLMRateLimitError("Gemini", retry_after=60)
            if "connection" in error_str or "network" in error_str:
                raise LLMConnectionError("Gemini", str(e))
            logger.error(f"Gemini error: {e}")
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
            
            response = self._model.generate_content(
                [self._get_system_prompt(), full_prompt],
                tools=gemini_tools if gemini_tools else None,
            )
            
            # Check if the model wants to call a function
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        return None, ToolExecutionResult(
                            tool_name=fc.name,
                            success=True,
                            result={"args": dict(fc.args)},
                        )
            
            # No function call, return text response
            return response.text, None
            
        except Exception as e:
            logger.error(f"Gemini function calling error: {e}")
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
