"""
Llama-cpp Local LLM Adapter for Amadeus AI.

Connects directly to a locally downloaded GGUF model via llama-cpp-python.
This provides a 100% offline, privacy-first local experience.

Designed to be used as the primary offline provider if SLM_MODEL_PATH is configured.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from src.core.exceptions import ConfigurationError, LLMConnectionError, LLMResponseError
from src.core.interfaces.services import ILLMService
from src.core.domain.models import ToolDefinition, ToolExecutionResult


if TYPE_CHECKING:
    from src.core.domain.models import ConversationContext


logger = logging.getLogger(__name__)


class LlamaCppAdapter(ILLMService):
    """
    Adapter for running local GGUF models directly via llama-cpp-python.

    Features:
    - Async streaming via AsyncIterator[str]
    - Isolated initialization to prevent blocking the main event loop
    - Conversation history injection from ConversationContext
    - Graceful parameter guards for version-sensitive llama_cpp options
    """

    def __init__(
        self,
        model_path: str,
        threads: int = 2,
        context_length: int = 2048,
    ) -> None:
        self.model_path = model_path
        self.threads = threads
        self.context_length = context_length
        self._llm: Any | None = None
        self._lock = asyncio.Lock()
        # Set to True after a fatal decode failure so we stop trying until restart
        self._failed: bool = False
        logger.info(
            "LlamaCppAdapter configured with model: %s (threads=%d, ctx=%d)",
            self.model_path,
            self.threads,
            self.context_length,
        )

    async def _get_llm(self) -> Any:
        """Lazily initialize the model to prevent massive blocking on startup."""
        if self._llm is not None:
            return self._llm

        async with self._lock:
            # Double-checked locking to prevent concurrent instantiation
            if self._llm is not None:
                return self._llm

            try:
                from llama_cpp import Llama

                logger.info("Initializing LlamaCpp (this may take a moment)...")

                # Build constructor kwargs — only include params that exist in
                # the installed llama_cpp version to avoid TypeError on older builds.
                init_kwargs: dict[str, Any] = {
                    "model_path": self.model_path,
                    "n_threads": self.threads,
                    "n_ctx": self.context_length,
                    "n_batch": 64,
                    "use_mmap": True,
                    "use_mlock": False,
                    "verbose": False,
                }

                # flash_attn / type_k / type_v are only available in llama_cpp >= 0.2.56
                # and only on some hardware builds. Guard them to stay version-safe.
                import inspect
                try:
                    # Inspect the class directly to avoid MagicMock __init__ issues in tests
                    llama_sig = inspect.signature(Llama)
                    if "flash_attn" in llama_sig.parameters:
                        init_kwargs["flash_attn"] = True
                    if "type_k" in llama_sig.parameters:
                        init_kwargs["type_k"] = 8  # q8_0 kv cache — less RAM
                    if "type_v" in llama_sig.parameters:
                        init_kwargs["type_v"] = 8
                except ValueError:
                    # If Llama is a compiled C-extension without a signature, fallback safely
                    logger.debug("Could not inspect Llama signature; using basic kwargs")

                # Load model in a separate thread to avoid blocking event loop
                self._llm = await asyncio.to_thread(Llama, **init_kwargs)
                logger.info("LlamaCpp initialized successfully.")

            except ImportError as exc:
                raise ConfigurationError(
                    "llama-cpp-python is not installed. "
                    "Install it with: pip install llama-cpp-python",
                    config_key="SLM_MODEL_PATH",
                ) from exc
            except Exception as e:
                logger.exception("Failed to load LlamaCpp model: %s", type(e).__name__)
                raise LLMConnectionError("LlamaCpp", f"Model load failed: {e}") from e

        return self._llm

    # =========================================================================
    # HEALTH & AVAILABILITY
    # =========================================================================

    async def is_available(self) -> bool:
        """Check if model path exists on disk."""
        import os

        if not os.path.exists(self.model_path):
            logger.warning("Llama model path not found: %s", self.model_path)
            return False
        return True

    # =========================================================================
    # HELPERS
    # =========================================================================

    # System prompt kept SHORT for a 1B model's limited context window.
    # The full identity template is used by cloud providers; this is the local-only version.
    _LOCAL_SYSTEM_PROMPT = (
        "You are Amadeus, an advanced AI assistant. "
        "You are helpful, direct, and concise. "
        "Always respond as Amadeus — never address the user as Amadeus. "
        "Keep responses plain text — no markdown formatting (no *, **, _, `, etc). "
        "Use numbered lists for structured output. "
        "If you don't know something, say so honestly."
    )

    @staticmethod
    def _build_messages(
        prompt: str,
        context: "ConversationContext | None",
        max_history_turns: int = 4,
    ) -> list[dict[str, str]]:
        """
        Build a chat-completion messages list from a prompt and optional context.

        To avoid overflowing the local model's limited context window (2048 tokens),
        we keep only the most recent `max_history_turns` exchanges (user+assistant pairs).
        A system message is always prepended so the model knows its identity.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": LlamaCppAdapter._LOCAL_SYSTEM_PROMPT}
        ]

        if context is not None:
            history = [
                msg for msg in getattr(context, "messages", [])
                if getattr(msg, "role", None) in ("user", "assistant")
            ]
            # Keep only the tail — last N turns to respect the 2048 ctx limit
            max_msgs = max_history_turns * 2  # each turn = user + assistant
            if len(history) > max_msgs:
                history = history[-max_msgs:]
                logger.debug(
                    "LlamaCpp: trimmed conversation history to last %d messages "
                    "(ctx limit guard)",
                    max_msgs,
                )
            for msg in history:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", None)
                if role and content:
                    messages.append({"role": str(role), "content": str(content)})

        # Always append the latest user turn
        messages.append({"role": "user", "content": prompt})
        return messages

    # =========================================================================
    # GENERATION
    # =========================================================================

    async def generate_response(
        self,
        prompt: str,
        context: "ConversationContext | None" = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Generate a full response from the local Llama model.

        Args:
            prompt:      The current user turn text.
            context:     Optional ConversationContext — conversation history is
                         injected into the messages list so the model has memory.
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
            max_tokens:  Maximum tokens to generate. Defaults to context_length.

        Returns:
            Generated text string.

        Raises:
            ConfigurationError:  Model path missing or library not installed.
            LLMConnectionError:  Model failed to load.
            LLMResponseError:    Generation failed at runtime.
        """
        if not await self.is_available():
            raise ConfigurationError(
                f"Llama model file not found at: {self.model_path}",
                config_key="SLM_MODEL_PATH",
            )

        # If a previous fatal decode error occurred, don't retry — fall through
        # to the next provider in the LLMRouter.
        if self._failed:
            raise LLMResponseError(
                "LlamaCpp is in a failed state (llama_decode error). "
                "Restart the server to reset."
            )

        llm = await self._get_llm()
        messages = self._build_messages(prompt, context)

        try:

            def _generate() -> str:
                res = llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens if max_tokens else self.context_length,
                    temperature=temperature,
                    stream=False,
                )
                return str(res["choices"][0]["message"]["content"]).strip()

            response_text = await asyncio.to_thread(_generate)
            logger.debug(
                "LlamaCpp generated %d chars (temp=%.2f, max_tokens=%s)",
                len(response_text),
                temperature,
                max_tokens,
            )
            return response_text
        except LLMResponseError:
            raise
        except Exception as e:
            err_str = str(e)
            if "llama_decode" in err_str or "GGML_ASSERT" in err_str:
                # Fatal decode failure — mark adapter as failed to prevent
                # repeated crashes on subsequent requests until server restarts.
                self._failed = True
                logger.error(
                    "LlamaCpp FATAL decode error — marking adapter as failed. "
                    "Subsequent requests will skip local model. Error: %s",
                    err_str,
                )
            else:
                logger.exception("Llama generation failed: %s", type(e).__name__)
            raise LLMResponseError(f"LlamaCpp generation failed: {e}") from e

    async def stream_response(
        self,
        prompt: str,
        context: "ConversationContext | None" = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from Llama one-by-one safely into the async loop.

        Args:
            prompt:      The current user turn text.
            context:     Optional ConversationContext for conversation history.
            temperature: Sampling temperature.
            max_tokens:  Maximum tokens to generate.

        Yields:
            Individual token strings as they are generated.
        """
        if not await self.is_available():
            yield "⚠️ Llama model path not available."
            return

        llm = await self._get_llm()
        messages = self._build_messages(prompt, context)
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _blocking_stream() -> None:
            try:
                stream = llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens if max_tokens else self.context_length,
                    temperature=temperature,
                    stream=True,
                )
                for chunk in stream:
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        loop.call_soon_threadsafe(queue.put_nowait, token)
            except Exception as e:
                logger.error("Llama stream error: %s", e)
                loop.call_soon_threadsafe(queue.put_nowait, f"\n⚠️ Stream interrupted: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # EOF marker

        # Run generator in separate thread
        task = asyncio.create_task(asyncio.to_thread(_blocking_stream))

        try:
            while True:
                token = await queue.get()
                if token is None:
                    break
                yield token
        finally:
            task.cancel()

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        context: "ConversationContext | None" = None,
    ) -> tuple[str | None, ToolExecutionResult | None]:
        """LlamaCpp doesn't support native function calling — fallback to text."""
        text = await self.generate_response(prompt, context)
        return text, None
