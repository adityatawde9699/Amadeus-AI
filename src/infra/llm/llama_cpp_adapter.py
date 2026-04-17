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


if TYPE_CHECKING:
    from src.core.domain.models import ConversationContext


logger = logging.getLogger(__name__)


class LlamaCppAdapter:
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
        logger.info(
            "LlamaCppAdapter configured with model: %s (threads=%d, ctx=%d)",
            self.model_path,
            self.threads,
            self.context_length,
        )

    async def _get_llm(self) -> Any:
        """Lazily initialize the model to prevent massive blocking on startup."""
        if self._llm is None:
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

                llama_sig = inspect.signature(Llama.__init__)
                if "flash_attn" in llama_sig.parameters:
                    init_kwargs["flash_attn"] = True
                if "type_k" in llama_sig.parameters:
                    init_kwargs["type_k"] = 8  # q8_0 kv cache — less RAM
                if "type_v" in llama_sig.parameters:
                    init_kwargs["type_v"] = 8

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
                raise LLMConnectionError(
                    "LlamaCpp", f"Model load failed: {e}"
                ) from e
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

    @staticmethod
    def _build_messages(
        prompt: str,
        context: "ConversationContext | None",
    ) -> list[dict[str, str]]:
        """
        Build a chat-completion messages list from a prompt and optional context.

        If *context* carries conversation history we inject it so the local model
        has the same multi-turn awareness as the cloud providers.
        """
        messages: list[dict[str, str]] = []

        if context is not None:
            # Inject conversation history from ConversationContext.messages
            for msg in getattr(context, "messages", []):
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
        max_tokens: int | None = 2048,
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
        except Exception as e:
            logger.exception("Llama generation failed: %s", type(e).__name__)
            raise LLMResponseError(f"LlamaCpp generation failed: {e}") from e

    async def stream_response(
        self,
        prompt: str,
        context: "ConversationContext | None" = None,
        temperature: float = 0.7,
        max_tokens: int | None = 2048,
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
                loop.call_soon_threadsafe(
                    queue.put_nowait, f"\n⚠️ Stream interrupted: {e}"
                )
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
