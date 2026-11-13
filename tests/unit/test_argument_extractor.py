"""ArgumentExtractor: LLM extraction, office/code generators and regex fast paths."""

from __future__ import annotations

import pytest

from src.app.services.argument_extractor import ArgumentExtractor
from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory


class _Router:
    """Minimal LLMRouter stand-in: returns canned text, records prompts."""

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **_: object) -> tuple[str, str]:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, "fake"


def _registry() -> ToolRegistry:
    reg = ToolRegistry()

    def get_weather(location: str, units: str = "metric") -> str:
        return location

    reg.register(
        Tool(
            name="get_weather",
            function=get_weather,
            description="weather",
            category=ToolCategory.WEATHER,
            parameters={"location": {"type": "string"}, "units": {"type": "string"}},
        )
    )
    return reg


def _extractor(reply: str | Exception | None = None) -> ArgumentExtractor:
    router = _Router(reply) if reply is not None else None
    return ArgumentExtractor(_registry(), router)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_llm_extraction_filters_to_schema_keys_and_strips_noise():
    ext = _extractor('Sure! ```json\n{"location": " Pune ", "bogus": "x", "units": ""}\n```')
    assert await ext.extract("get_weather", "what's the weather in Pune today") == {
        "location": "Pune"
    }


@pytest.mark.asyncio
async def test_llm_prompt_fences_user_input_as_data():
    ext = _extractor('{"location": "x"}')
    await ext.extract("get_weather", "weather in <b>Pune</b> please")
    prompt = ext._llm_router.prompts[0]  # type: ignore[union-attr]
    assert "<user_input>" in prompt and "&lt;b&gt;Pune&lt;/b&gt;" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["not json at all", RuntimeError("down"), "{}"])
async def test_llm_failure_falls_back_to_fast_path(reply):
    ext = _extractor(reply)
    assert await ext.extract("get_weather", "weather in Mumbai") == {"location": "mumbai"}


@pytest.mark.asyncio
async def test_excel_and_word_use_llm_then_defaults():
    ext = _extractor('{"file_name": "q3.xlsx", "columns": ["a"], "data": [[1]]}')
    assert await ext.extract("create_excel_spreadsheet", "make a sheet") == {
        "file_name": "q3.xlsx",
        "columns": ["a"],
        "data": [[1]],
    }
    no_llm = _extractor()
    assert (await no_llm.extract("create_excel_spreadsheet", "x"))["file_name"] == (
        "spreadsheet.xlsx"
    )
    word = await _extractor(RuntimeError("x")).extract("create_word_document", "a memo")
    assert word == {"file_name": "document.docx", "title": "Untitled Document", "content": "a memo"}
    word_ok = await _extractor('<think>hmm</think>```{"title": "T"}```').extract(
        "create_word_document", "x"
    )
    assert word_ok["title"] == "T"


@pytest.mark.asyncio
async def test_code_generation_only_for_natural_language():
    ext = _extractor("```python\nprint(42)\n```")
    assert await ext.extract("execute_python_script", "print the answer") == {"code": "print(42)"}
    # Already code: goes to the fast path untouched.
    assert await ext.extract("execute_python_script", "x = 1") == {"query": "x = 1"}
    failed = await _extractor(RuntimeError("x")).extract("execute_python_script", "add numbers")
    assert failed["code"].startswith("# Error generating code")


@pytest.mark.parametrize(
    ("tool", "text", "expected"),
    [
        ("open_program", "please open Firefox", {"app_name": "Firefox"}),
        ("open_program", "Firefox", {"app_name": "Firefox"}),
        ("terminate_program", "kill chrome", {"process_name": "chrome"}),
        ("search_file", "find a file named report.pdf", {"file_name": "report.pdf"}),
        (
            "web_search",
            "Amadeus, please search for rust lifetimes on google",
            {"query": "rust lifetimes"},
        ),
        ("get_weather", "weather forecast for New York", {"location": "new york"}),
        ("get_weather", "how is the weather", {"location": "current location"}),
        (
            "get_news",
            "latest tech news in usa",
            {"category": "technology", "country": "us", "count": 5},
        ),
        ("get_news", "headlines", {"category": "general", "country": "in", "count": 5}),
        ("set_volume", "mute", {"level": -1}),
        ("set_volume", "unmute the audio", {"level": -2}),
        ("set_volume", "volume 30%", {"level": 30}),
        ("set_volume", "max volume", {"level": 100}),
        ("set_brightness", "dim the screen", {"level": 20}),
        ("set_brightness", "brightness 55", {"level": 55}),
        ("take_screenshot", "screenshot please", {}),
        ("calculate", "what is 2+2", {"expression": "2+2"}),
        ("create_note", "save note buy milk", {"content": "buy milk"}),
        ("set_timer", "timer for 2 minutes", {"duration_seconds": 120}),
        ("set_timer", "45 seconds", {"duration_seconds": 45}),
        ("set_timer", "a timer", {"duration_seconds": 300}),
        ("convert_length", "5 km in miles", {"expression": "5 km in miles"}),
        ("unknown_tool", "whatever", {"query": "whatever"}),
    ],
)
@pytest.mark.asyncio
async def test_fast_paths(tool, text, expected):
    assert await _extractor().extract(tool, text) == expected


@pytest.mark.asyncio
async def test_reminder_splits_subject_and_time():
    args = await _extractor().extract("add_reminder", "remind me to call mom in 30 minutes")
    assert args == {"title": "call mom", "time": "in 30 minutes"}
