"""Rule-based tool arguments: filled exactly, or None so the LLM takes over."""

from __future__ import annotations

import pytest

from src.app.services.slot_extractor import extract_slots
from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory


@pytest.mark.parametrize(
    ("tool", "text", "expected"),
    [
        ("calculate", "what is 17 times 23", {"expression": "17 * 23"}),
        ("calculate", "how much is 15 percent of 240?", {"expression": "(15 / 100) * 240"}),
        ("calculate", "2 to the power of 10", {"expression": "2 ** 10"}),
        ("calculate", "what is the meaning of life", None),
        (
            "convert_temperature",
            "convert 100 fahrenheit to celsius",
            {"value": 100.0, "from_unit": "F", "to_unit": "C"},
        ),
        (
            "convert_temperature",
            "what is 72 F in C",
            {"value": 72.0, "from_unit": "F", "to_unit": "C"},
        ),
        (
            "convert_length",
            "how many kilometers is 26 miles",
            {"value": 26.0, "from_unit": "mi", "to_unit": "km"},
        ),
        (
            "convert_length",
            "how many centimeters are in 6 feet",
            {"value": 6.0, "from_unit": "ft", "to_unit": "cm"},
        ),
        ("convert_length", "convert 5 parsecs to km", None),
        (
            "convert_currency",
            "how much is 75 dollars in rupees",
            {"amount": 75.0, "from_currency": "USD", "to_currency": "INR"},
        ),
        ("get_weather", "weather in Mumbai right now", {"location": "Mumbai"}),
        ("get_weather", "is it raining", {}),
        ("get_datetime_info", "what time is it", {"query": "time"}),
        ("get_crypto_price", "what's the bitcoin price", {"coin": "bitcoin"}),
        ("get_crypto_price", "how are my coins doing", None),
        ("get_stock_price", "how is AAPL stock doing today", {"symbol": "AAPL"}),
        ("get_stock_price", "check the tesla share price", {"symbol": "TSLA"}),
        ("get_stock_price", "how is the market", None),
        ("web_search", "search the web for cheap flights", {"query": "cheap flights"}),
        ("wikipedia_search", "who was Ada Lovelace?", {"query": "Ada Lovelace"}),
        (
            "search_codebase",
            "find where the login handler is defined in the codebase",
            {"query": "login handler"},
        ),
        (
            "fetch_webpage_content",
            "summarise https://example.org/a.",
            {"url": "https://example.org/a"},
        ),
        ("fetch_webpage_content", "summarise that page", None),
        ("ping_host", "ping google.com", {"host": "google.com"}),
        ("ping_host", "ping my server", None),
        ("fs_read_file", "read the file notes/todo.md", {"path": "notes/todo.md"}),
        ("fs_read_file", "read that file", None),
        ("fs_list_directory", "list the files in the docs directory", {"path": "docs"}),
        ("fs_list_directory", "what's in the current folder", {"path": "."}),
        ("open_program", "could you open slack", {"app_name": "slack"}),
        ("terminate_program", "kill the zoom app", {"process_name": "zoom"}),
        ("add_task", "add a task to renew my passport", {"task_content": "renew my passport"}),
        ("add_task", "put buy milk on my todo list", {"task_content": "buy milk"}),
        ("create_note", "take a note: gate code is 9921", {"content": "gate code is 9921"}),
        (
            "add_reminder",
            "remind me to call the vet in 45 minutes",
            {"title": "call the vet", "time": "in 45 minutes"},
        ),
        ("add_reminder", "remind me to call the vet", None),
        ("set_timer", "set a timer for 12 minutes", {"duration_seconds": 720}),
        ("set_timer", "set a timer", None),
        ("start_pomodoro", "start a 50 minute pomodoro", {"duration": 50}),
        (
            "store_core_memory",
            "remember that my car is on level 3",
            {"fact": "my car is on level 3"},
        ),
        ("list_tasks", "show my pending tasks", {"status_filter": "pending"}),
        ("decompose_goal", "break goal 3 into steps", {"goal_id": 3}),
        ("take_screenshot", "take a screenshot", {}),
    ],
)
def test_extract_slots(tool, text, expected):
    assert extract_slots(tool, text) == expected


def test_tools_without_an_extractor():
    reg = ToolRegistry()
    reg.register(
        Tool(name="no_args", function=lambda: "x", category=ToolCategory.SYSTEM, description="d")
    )
    reg.register(
        Tool(
            name="defaults",
            function=lambda path="/", count=3: "x",
            category=ToolCategory.SYSTEM,
            description="d",
        )
    )
    reg.register(
        Tool(
            name="needs",
            function=lambda code=None: "x",
            category=ToolCategory.SYSTEM,
            description="d",
        )
    )
    reg.register(
        Tool(name="required", function=lambda q: "x", category=ToolCategory.SYSTEM, description="d")
    )
    assert extract_slots("no_args", "go", reg) == {}
    assert extract_slots("defaults", "go", reg) == {}
    assert extract_slots("needs", "go", reg) is None  # None default = expected argument
    assert extract_slots("required", "go", reg) is None
    assert extract_slots("unknown", "go", reg) is None
    assert extract_slots("unknown", "go") is None
