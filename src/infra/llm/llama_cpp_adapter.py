"""
Llama-cpp Local LLM Adapter for Amadeus AI.

Connects directly to a locally downloaded GGUF model via llama-cpp-python.
This provides a 100% offline, privacy-first local experience.

Designed to be used as the primary offline provider if SLM_MODEL_PATH is configured.

Supports optional 4-bit KV-cache quantization (type_k / type_v) to reduce
RAM usage during inference — especially useful for large context windows on
memory-constrained machines.
"""


import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.domain.models import ToolDefinition, ToolExecutionResult
from src.core.exceptions import ConfigurationError, LLMConnectionError, LLMResponseError
from src.core.interfaces.services import ILLMService


if TYPE_CHECKING:
    from src.core.domain.models import ConversationContext


logger = logging.getLogger(__name__)

# ── GGML quantization type constants ─────────────────────────────────────────
# These mirror the ggml_type enum from llama.cpp.
# We only reference the ones needed for 4-bit KV-cache quantization.
GGML_TYPE_F16 = 1      # 16-bit float  (default KV cache type)
GGML_TYPE_Q4_0 = 2     # 4-bit quantization  (symmetric, fastest)
GGML_TYPE_Q4_1 = 3     # 4-bit quantization  (asymmetric, slightly better quality)
GGML_TYPE_Q8_0 = 8     # 8-bit quantization  (good quality / size tradeoff)

# ── Qwen3 / chain-of-thought stripping ──────────────────────────────────────────────
import re as _re


_THINK_TAG_RE = _re.compile(r"<think>[\s\S]*?</think>", _re.IGNORECASE)

# Matches verbose thinking preambles that Qwen3 emits *outside* <think> tags,
# e.g. "Let me think through this carefully." / "Thinking Process:" / numbered
# analysis steps like "1.  **Analyze the Request:**" / meta-analysis like
# "The user is asking me to..." / self-narration like "I need to...".
_PREAMBLE_RE = _re.compile(
    r"^(?:"
    # "Let me think/work/analyze..."
    r"(?:let me (?:think|work|analyze|break|reason|consider|figure|look)(?:[\s\S]*?(?:\n\n|\Z)))"
    # "Thinking process:"
    r"|(?:thinking process:?[\s\S]*?(?:\n\n|\Z))"
    # "Okay, ..." / "Alright, ..."
    r"|(?:(?:okay|alright|sure)(?:,| )[\s\S]*?(?:\n\n|\Z))"
    # Numbered bold steps: "1.  **Analyze:**"
    r"|(?:(?:\d+\.\s+\*\*[\s\S]*?(?:\n\n|\Z))+)"
    # Meta-analysis: "The user is asking/wants/needs..."
    r"|(?:the user (?:is|wants|needs|asked|seems|would)[\s\S]*?(?:\n\n|\Z))"
    # Self-narration: "I need to/should/will/must..."
    r"|(?:i (?:need to|should|will|must|have to|can|want to)[\s\S]*?(?:\n\n|\Z))"
    # "Here's my/a/the ..."
    r"|(?:here(?:'s| is) (?:my|a|the)[\s\S]*?(?:\n\n|\Z))"
    # "First, I'll/let's/we need..."
    r"|(?:first(?:,|ly)?\s[\s\S]*?(?:\n\n|\Z))"
    r")",
    _re.IGNORECASE | _re.MULTILINE,
)

# Matches numbered plain-text reasoning lines ("1. The user wants X\n2. I need to Y")
# that appear as multi-line CoT without bold formatting.
_NUMBERED_COT_RE = _re.compile(
    r"^(?:\d+\.\s+(?:the user|i need|i should|i will|i must|i have to|i want to|check|analyze|compose|respond|this)[^\n]*\n?)+",
    _re.IGNORECASE | _re.MULTILINE,
)


def _strip_think_tags(text: str) -> str:
    """Remove Qwen3-style chain-of-thought content from model output.

    Handles four variants:
      1. Full tags:     <think>...reasoning...</think>\nFinal answer
      2. Truncated:    ...reasoning...\n</think>\nFinal answer
                       (model omits the opening tag; everything before </think> is CoT)
      3. Untagged CoT: "Let me think through this carefully..." preambles that
                       Qwen3 sometimes emits without wrapping in <think> tags.
      4. Numbered CoT: "1. The user wants X\n2. I need to Y" style analysis.
    """
    # 1. Strip matched pairs first
    cleaned = _THINK_TAG_RE.sub("", text)
    # 2. If a lone </think> remains, strip everything before it (inclusive)
    lone_close = cleaned.find("</think>")
    if lone_close == -1:
        lone_close = cleaned.lower().find("</think>")
    if lone_close != -1:
        cleaned = cleaned[lone_close + len("</think>"):]
    # 3. Strip untagged thinking preambles
    cleaned = _PREAMBLE_RE.sub("", cleaned)
    # 4. Strip numbered CoT reasoning lines
    cleaned = _NUMBERED_COT_RE.sub("", cleaned)
    return cleaned.strip()


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
        quantize_kv_4bit: bool = False,
    ) -> None:
        self.model_path = model_path
        self.threads = threads
        self.context_length = context_length
        self.quantize_kv_4bit = quantize_kv_4bit
        self._llm: Any | None = None
        self._lock = asyncio.Lock()
        # Set to True after a fatal decode failure so we stop trying until restart
        self._failed: bool = False
        logger.info(
            "LlamaCppAdapter configured with model: %s "
            "(threads=%d, ctx=%d, kv_4bit=%s)",
            self.model_path,
            self.threads,
            self.context_length,
            self.quantize_kv_4bit,
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

                # ── Optional parameters gated by version inspection ────────
                # Some llama-cpp-python builds lack flash_attn / type_k / type_v.
                # We only inject them when the installed version supports them.
                import inspect
                try:
                    llama_sig = inspect.signature(Llama)

                    # flash_attn — leave disabled on CPU by default
                    if "flash_attn" in llama_sig.parameters:
                        init_kwargs["flash_attn"] = False

                    # ── 4-bit KV-cache quantization ────────────────────────
                    # When enabled, quantizes the key/value cache from FP16
                    # to Q4_0.  Cuts KV-cache memory by ~75% at the cost of
                    # a small quality loss — ideal for large context windows
                    # on memory-constrained hardware.
                    if self.quantize_kv_4bit:
                        supports_type_k = "type_k" in llama_sig.parameters
                        supports_type_v = "type_v" in llama_sig.parameters

                        if supports_type_k and supports_type_v:
                            init_kwargs["type_k"] = GGML_TYPE_Q4_0
                            init_kwargs["type_v"] = GGML_TYPE_Q4_0
                            logger.info(
                                "4-bit KV-cache quantization ENABLED "
                                "(type_k=Q4_0, type_v=Q4_0)"
                            )
                        else:
                            missing = []
                            if not supports_type_k:
                                missing.append("type_k")
                            if not supports_type_v:
                                missing.append("type_v")
                            logger.warning(
                                "4-bit KV-cache quantization requested but "
                                "llama-cpp-python build lacks param(s): %s. "
                                "Falling back to FP16 KV cache.",
                                ", ".join(missing),
                            )
                except ValueError:
                    logger.debug("Could not inspect Llama signature; using basic kwargs")

                # Load model in a separate thread to avoid blocking event loop
                try:
                    self._llm = await asyncio.to_thread(Llama, **init_kwargs)
                except ValueError as e:
                    if self.quantize_kv_4bit and ("type_k" in init_kwargs or "type_v" in init_kwargs):
                        logger.warning(
                            "Failed to initialize Llama with 4-bit KV cache (likely model/arch incompatible). "
                            "Falling back to standard FP16 KV cache. Error: %s", e
                        )
                        # Remove quantization params and try again
                        init_kwargs.pop("type_k", None)
                        init_kwargs.pop("type_v", None)
                        self._llm = await asyncio.to_thread(Llama, **init_kwargs)
                    else:
                        raise

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
        if not Path(self.model_path).exists():
            logger.warning("Llama model path not found: %s", self.model_path)
            return False
        return True

    # =========================================================================
    # HELPERS
    # =========================================================================

    # System prompt kept SHORT for a 1B model's limited context window.
    # The full identity template is used by cloud providers; this is the local-only version.
    # /no_think disables Qwen3's chain-of-thought mode so it never emits <think> blocks.
    _LOCAL_SYSTEM_PROMPT = (
        "/no_think "
        "You are Amadeus, an advanced local AI assistant. "
        "Be direct, intelligent, concise, and practical. "
        "Prioritize accuracy over politeness. "
        "Never reveal chain-of-thought, internal reasoning, hidden analysis, or step-by-step thinking. "
        "Never output thoughts inside tags such as: <think>, <reason>, <analysis>, or similar. "
        "Do not explain internal decision-making. "
        "Output only the final answer. "
        "Keep responses plain text — no markdown formatting (no *, **, _, `, etc). "
        "Use numbered lists for structured output. "
        "If you don't know something, say: I don't know. "
        "Never say 'The user is asking' or 'I need to' — just respond directly."
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
                raw = str(res["choices"][0]["message"]["content"]).strip()
                return _strip_think_tags(raw)

            response_text = await asyncio.to_thread(_generate)
            if not response_text:
                raise LLMResponseError(
                    "LlamaCpp returned empty response after think-tag stripping — "
                    "falling through to next provider"
                )
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
                logger.exception(
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
                # Accumulate tokens; strip <think> blocks from the
                # completed text before forwarding to avoid leaking CoT.
                accumulated: list[str] = []
                in_think_block = False
                for chunk in stream:
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    token = delta.get("content", "")
                    if not token:
                        continue
                    accumulated.append(token)
                    joined = "".join(accumulated)
                    # Detect opening tag — enter suppression mode
                    if "<think>" in joined.lower() and not in_think_block:
                        in_think_block = True
                    # Detect closing tag — flush only the text AFTER </think>
                    if in_think_block and "</think>" in joined.lower():
                        after = _THINK_TAG_RE.sub("", joined).strip()
                        accumulated = [after]  # reset buffer to remainder
                        in_think_block = False
                        if after:
                            loop.call_soon_threadsafe(queue.put_nowait, after)
                        continue
                    # Normal (non-think) token — emit immediately
                    if not in_think_block:
                        loop.call_soon_threadsafe(queue.put_nowait, token)
            except Exception as e:
                logger.exception("Llama stream error: %s", e)
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
