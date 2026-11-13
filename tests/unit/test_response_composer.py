"""ResponseComposer: prompt assembly, untrusted-data fencing and output cleanup."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.app.services.response_composer import ResponseComposer


class _Router:
    def __init__(self, reply="ok", providers=None, fail=False):
        self.reply, self.fail = reply, fail
        self._providers = providers or {}
        self.calls: list[dict] = []

    async def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.fail:
            raise RuntimeError("router down")
        return self.reply, "fake"


class _Memory:
    is_enabled = True

    def __init__(self, fail=False):
        self.fail = fail

    async def retrieve(self, query, top_k=3):
        if self.fail:
            raise RuntimeError("vector store down")
        return ["m1"]

    def format_for_prompt(self, memories, max_chars=600):
        return "user likes <tea>"


def _settings(local_only=False):
    return SimpleNamespace(LOCAL_ONLY_MODE=local_only)


@pytest.mark.asyncio
async def test_system_prompt_includes_fenced_memories_and_survives_failures():
    composer = ResponseComposer(None, _settings(), _Memory())
    prompt = await composer.build_system_prompt("s1", "summary", user_query="drink?")
    assert "[RETRIEVED MEMORIES]" in prompt and "user likes" in prompt
    assert prompt.endswith("[USER MESSAGE]\n")
    failing = ResponseComposer(None, _settings(), _Memory(fail=True))
    assert "[RETRIEVED MEMORIES]" not in await failing.build_system_prompt("s", "", "q")
    no_query = await composer.build_system_prompt("s", "", "")
    assert "[RETRIEVED MEMORIES]" not in no_query


@pytest.mark.asyncio
async def test_tool_response_fences_output_and_falls_back_to_raw():
    router = _Router("RESPONSE: The CPU is at 12%.")
    composer = ResponseComposer(router, _settings())  # type: ignore[arg-type]
    assert await composer.compose_tool_response("cpu?", "get_cpu", "cpu=12") == "The CPU is at 12%."
    prompt = router.calls[0]["prompt"]
    assert "<user_task>" in prompt and "untrusted" in prompt.lower()
    broken = ResponseComposer(_Router(fail=True), _settings())  # type: ignore[arg-type]
    assert await broken.compose_tool_response("q", "t", "raw output") == "raw output"
    assert await ResponseComposer(None, _settings()).compose_tool_response("q", "t", "raw") == "raw"


@pytest.mark.asyncio
async def test_conversational_uses_compact_prompt_for_local_and_respects_local_only():
    local = _Router("Hi!", providers={"llama_cpp": object()})
    composer = ResponseComposer(local, _settings(local_only=True))  # type: ignore[arg-type]
    assert await composer.compose_conversational("hello", "s", "", "", complexity="high") == "Hi!"
    call = local.calls[0]
    assert call["complexity"] == "normal"  # 'high' would reach the cloud
    assert call["max_tokens"] == 256 and "Respond in 1-2 sentences" in call["prompt"]

    cloud = _Router("Sure.")
    await ResponseComposer(cloud, _settings()).compose_conversational(  # type: ignore[arg-type]
        "hello", "s", "", "", complexity="high"
    )
    assert cloud.calls[0]["max_tokens"] == 512 and "Recent conversation" in cloud.calls[0]["prompt"]

    down = ResponseComposer(_Router(fail=True), _settings())  # type: ignore[arg-type]
    assert "trouble" in await down.compose_conversational("x", "s", "", "")


@pytest.mark.asyncio
async def test_long_form():
    router = _Router("A long essay.")
    composer = ResponseComposer(router, _settings())  # type: ignore[arg-type]
    assert await composer.compose_long_form("essay", "s", "", "") == "A long essay."
    assert router.calls[0]["complexity"] == "high" and router.calls[0]["max_tokens"] == 1024
    down = ResponseComposer(_Router(fail=True), _settings())  # type: ignore[arg-type]
    assert "trouble" in await down.compose_long_form("x", "s", "", "")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Paris is the capital.", "Paris is the capital."),
        ("The user wants the capital. Paris is the capital", "Paris is the capital."),
        ("I need to answer. Looking at the data. It is 4", "It is 4."),
        ("", ""),
    ],
)
def test_sanitize_llm_output_drops_meta_narration(raw, clean):
    assert ResponseComposer._sanitize_llm_output(raw) == clean
