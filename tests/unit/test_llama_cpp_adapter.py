"""
Unit tests for LlamaCppAdapter.

Tests cover:
- is_available() path checks
- generate_response() happy path and error propagation
- stream_response() token streaming
- _build_messages() conversation history injection
- Parameter guarding for flash_attn / type_k / type_v
- Correct exception types (ConfigurationError, LLMConnectionError, LLMResponseError)
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import ConfigurationError, LLMConnectionError, LLMResponseError
from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def model_path(tmp_path: Path) -> str:
    """Return path to a temporary fake GGUF file that exists on disk."""
    fake_model = tmp_path / "test_model.gguf"
    fake_model.write_bytes(b"\x00" * 64)  # Minimal fake content
    return str(fake_model)


@pytest.fixture
def adapter(model_path: str) -> LlamaCppAdapter:
    """Return a LlamaCppAdapter pointing at the fake model file."""
    return LlamaCppAdapter(model_path=model_path, threads=1, context_length=512)


def _make_fake_llama(response_text: str = "Hello from LlamaCpp!") -> MagicMock:
    """Build a mock llama_cpp.Llama instance that returns a canned response."""
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": response_text}, "finish_reason": "stop"}]
    }
    return llm


# =============================================================================
# is_available()
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_available_returns_true_when_file_exists(adapter: LlamaCppAdapter) -> None:
    """is_available() returns True when the model file exists."""
    assert await adapter.is_available() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_available_returns_false_when_file_missing() -> None:
    """is_available() returns False when the model path does not exist."""
    adapter = LlamaCppAdapter(model_path="/nonexistent/model.gguf")
    assert await adapter.is_available() is False


# =============================================================================
# _build_messages()
# =============================================================================


@pytest.mark.unit
def test_build_messages_no_context() -> None:
    """Without context, system message + user message are in the list."""
    msgs = LlamaCppAdapter._build_messages("Hello", context=None)
    assert msgs == [
        {"role": "system", "content": LlamaCppAdapter._LOCAL_SYSTEM_PROMPT},
        {"role": "user", "content": "Hello"}
    ]


@pytest.mark.unit
def test_build_messages_with_context_history() -> None:
    """With context, system prompt + previous messages are prepended."""
    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "What is Python?"

    msg2 = MagicMock()
    msg2.role = "assistant"
    msg2.content = "Python is a programming language."

    context = MagicMock()
    context.messages = [msg1, msg2]

    msgs = LlamaCppAdapter._build_messages("Tell me more.", context=context)

    assert msgs == [
        {"role": "system", "content": LlamaCppAdapter._LOCAL_SYSTEM_PROMPT},
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
        {"role": "user", "content": "Tell me more."},
    ]


@pytest.mark.unit
def test_build_messages_context_with_no_messages_attr() -> None:
    """Context objects without .messages don't crash — falls back to system + single turn."""
    context = MagicMock(spec=[])  # No .messages attribute
    msgs = LlamaCppAdapter._build_messages("Hi", context=context)
    assert msgs == [
        {"role": "system", "content": LlamaCppAdapter._LOCAL_SYSTEM_PROMPT},
        {"role": "user", "content": "Hi"}
    ]


# =============================================================================
# generate_response() — happy path
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_response_returns_text(adapter: LlamaCppAdapter) -> None:
    """generate_response() returns stripped text from the model."""
    fake_llm = _make_fake_llama("  Mocked response.  ")

    with patch(
        "src.infra.llm.llama_cpp_adapter.LlamaCppAdapter._get_llm",
        new=AsyncMock(return_value=fake_llm),
    ):
        result = await adapter.generate_response("Hello?")

    assert result == "Mocked response."
    fake_llm.create_chat_completion.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_response_passes_temperature_and_max_tokens(
    adapter: LlamaCppAdapter,
) -> None:
    """generate_response() forwards temperature and max_tokens to llama."""
    fake_llm = _make_fake_llama("ok")

    with patch(
        "src.infra.llm.llama_cpp_adapter.LlamaCppAdapter._get_llm",
        new=AsyncMock(return_value=fake_llm),
    ):
        await adapter.generate_response("Hi", temperature=0.3, max_tokens=128)

    call_kwargs = fake_llm.create_chat_completion.call_args.kwargs
    assert call_kwargs["temperature"] == pytest.approx(0.3)
    assert call_kwargs["max_tokens"] == 128
    assert call_kwargs["stream"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_response_injects_context_history(adapter: LlamaCppAdapter) -> None:
    """generate_response() includes conversation history from context."""
    fake_llm = _make_fake_llama("Sure!")

    prev = MagicMock()
    prev.role = "user"
    prev.content = "Previous question"
    context = MagicMock()
    context.messages = [prev]

    with patch(
        "src.infra.llm.llama_cpp_adapter.LlamaCppAdapter._get_llm",
        new=AsyncMock(return_value=fake_llm),
    ):
        await adapter.generate_response("Follow-up", context=context)

    sent_messages = fake_llm.create_chat_completion.call_args.kwargs["messages"]
    assert sent_messages[0] == {"role": "system", "content": LlamaCppAdapter._LOCAL_SYSTEM_PROMPT}
    assert sent_messages[1] == {"role": "user", "content": "Previous question"}
    assert sent_messages[2] == {"role": "user", "content": "Follow-up"}


# =============================================================================
# generate_response() — error cases
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_response_raises_configuration_error_when_path_missing() -> None:
    """generate_response() raises ConfigurationError when model file is absent."""
    adapter = LlamaCppAdapter(model_path="/does/not/exist.gguf")
    with pytest.raises(ConfigurationError):
        await adapter.generate_response("Hello")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_response_raises_llm_response_error_on_runtime_failure(
    adapter: LlamaCppAdapter,
) -> None:
    """generate_response() wraps runtime llama errors in LLMResponseError."""
    fake_llm = MagicMock()
    fake_llm.create_chat_completion.side_effect = RuntimeError("CUDA OOM")

    with patch(
        "src.infra.llm.llama_cpp_adapter.LlamaCppAdapter._get_llm",
        new=AsyncMock(return_value=fake_llm),
    ), pytest.raises(LLMResponseError, match="LlamaCpp generation failed"):
        await adapter.generate_response("Hello")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_llm_raises_configuration_error_on_import_failure(
    adapter: LlamaCppAdapter,
) -> None:
    """_get_llm() raises ConfigurationError when llama_cpp is not installed."""
    with patch.dict("sys.modules", {"llama_cpp": None}):
        with pytest.raises(ConfigurationError, match="llama-cpp-python is not installed"):
            await adapter._get_llm()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_llm_raises_llm_connection_error_on_load_failure(
    adapter: LlamaCppAdapter,
) -> None:
    """_get_llm() wraps non-import Llama init failures in LLMConnectionError."""
    mock_llama_module = MagicMock()
    mock_llama_module.Llama.side_effect = MemoryError("Out of memory")

    with patch.dict("sys.modules", {"llama_cpp": mock_llama_module}):
        with pytest.raises(LLMConnectionError, match="Model load failed"):
            await adapter._get_llm()


# =============================================================================
# stream_response()
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_response_yields_tokens(adapter: LlamaCppAdapter) -> None:
    """stream_response() yields each token from the llama stream."""

    def _make_chunk(content: str) -> dict[str, Any]:
        return {"choices": [{"delta": {"content": content}, "finish_reason": None}]}

    fake_stream = [_make_chunk("Hello"), _make_chunk(" world"), _make_chunk("!")]

    fake_llm = MagicMock()
    fake_llm.create_chat_completion.return_value = iter(fake_stream)

    with patch(
        "src.infra.llm.llama_cpp_adapter.LlamaCppAdapter._get_llm",
        new=AsyncMock(return_value=fake_llm),
    ):
        tokens = []
        async for token in adapter.stream_response("Hi"):
            tokens.append(token)

    assert tokens == ["Hello", " world", "!"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_response_yields_warning_when_path_missing() -> None:
    """stream_response() yields a warning string when model file is absent."""
    adapter = LlamaCppAdapter(model_path="/no/such/file.gguf")
    tokens = []
    async for token in adapter.stream_response("Hi"):
        tokens.append(token)

    assert len(tokens) == 1
    assert "⚠️" in tokens[0]


# =============================================================================
# Parameter guarding (#4 from audit)
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_llm_skips_flash_attn_when_not_supported(
    adapter: LlamaCppAdapter,
) -> None:
    """_get_llm() does not pass flash_attn when the llama_cpp version lacks it."""
    captured_kwargs: dict[str, Any] = {}

    def fake_llama_init(**kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return MagicMock()

    mock_llama_cls = MagicMock(side_effect=fake_llama_init)

    mock_module = MagicMock()
    mock_module.Llama = mock_llama_cls

    import inspect as _inspect
    fake_sig = _inspect.signature(
        lambda model_path, n_threads, n_ctx, n_batch, use_mmap, use_mlock, verbose: None
    )

    with patch.dict("sys.modules", {"llama_cpp": mock_module}):
        with patch("inspect.signature", return_value=fake_sig):
            await adapter._get_llm()

    # flash_attn / type_k / type_v must NOT be in the call
    assert "flash_attn" not in captured_kwargs
    assert "type_k" not in captured_kwargs
    assert "type_v" not in captured_kwargs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_llm_injects_4bit_kv_quantization_when_enabled(
    model_path: str,
) -> None:
    """_get_llm() passes type_k and type_v as GGML_TYPE_Q4_0 when quantize_kv_4bit=True."""
    from src.infra.llm.llama_cpp_adapter import GGML_TYPE_Q4_0

    adapter = LlamaCppAdapter(
        model_path=model_path, threads=1, context_length=512, quantize_kv_4bit=True,
    )

    captured_kwargs: dict[str, Any] = {}

    def fake_llama_init(**kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return MagicMock()

    mock_llama_cls = MagicMock(side_effect=fake_llama_init)

    mock_module = MagicMock()
    mock_module.Llama = mock_llama_cls

    import inspect as _inspect
    # Simulate a build that supports type_k / type_v / flash_attn
    fake_sig = _inspect.signature(
        lambda model_path, n_threads, n_ctx, n_batch, use_mmap, use_mlock,
               verbose, flash_attn, type_k, type_v: None
    )

    with patch.dict("sys.modules", {"llama_cpp": mock_module}):
        with patch("inspect.signature", return_value=fake_sig):
            await adapter._get_llm()

    assert captured_kwargs["type_k"] == GGML_TYPE_Q4_0
    assert captured_kwargs["type_v"] == GGML_TYPE_Q4_0
    assert captured_kwargs["flash_attn"] is False  # still disabled by default


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_llm_skips_4bit_kv_when_disabled(
    adapter: LlamaCppAdapter,
) -> None:
    """_get_llm() does NOT pass type_k/type_v when quantize_kv_4bit is False (default)."""
    captured_kwargs: dict[str, Any] = {}

    def fake_llama_init(**kwargs: Any) -> MagicMock:
        captured_kwargs.update(kwargs)
        return MagicMock()

    mock_llama_cls = MagicMock(side_effect=fake_llama_init)

    mock_module = MagicMock()
    mock_module.Llama = mock_llama_cls

    import inspect as _inspect
    fake_sig = _inspect.signature(
        lambda model_path, n_threads, n_ctx, n_batch, use_mmap, use_mlock,
               verbose, flash_attn, type_k, type_v: None
    )

    with patch.dict("sys.modules", {"llama_cpp": mock_module}):
        with patch("inspect.signature", return_value=fake_sig):
            await adapter._get_llm()

    # type_k / type_v should NOT be present since quantize_kv_4bit defaults to False
    assert "type_k" not in captured_kwargs
    assert "type_v" not in captured_kwargs

