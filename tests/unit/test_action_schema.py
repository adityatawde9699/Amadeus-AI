"""
P3: schema-constrained tool selection (llama.cpp grammar decoding).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.services.action_schema import (
    FINISH,
    MAX_PER_TOOL_BRANCHES,
    build_action_schema,
    tool_args_schema,
)
from src.infra.tools.base import Tool, ToolCategory


jsonschema = pytest.importorskip("jsonschema")


def _weather(location: str, units: str | None = None, **kwargs) -> str:
    return location


def _count(n: int = 3) -> str:
    return str(n)


def _tool(name, fn, category=ToolCategory.WEATHER, parameters=None):
    return Tool(name=name, function=fn, description="d", category=category,
                parameters=parameters or {})


def test_args_schema_uses_signature_names_and_types():
    schema = tool_args_schema(
        _tool("get_weather", _weather, parameters={"units": {"type": "string"}})
    )
    assert schema["properties"] == {"location": {"type": "string"}, "units": {"type": "string"}}
    assert schema["required"] == ["location"]
    assert schema["additionalProperties"] is False  # **kwargs is not exposed


def test_per_tool_schema_accepts_valid_and_rejects_invented_actions():
    schema = build_action_schema(
        [_tool("get_weather", _weather), _tool("count", _count, ToolCategory.CALCULATION)],
        lead="plan",
    )
    ok = [
        {"plan": "p", "tool": "get_weather", "args": {"location": "Pune"}},
        {"plan": "p", "tool": "count", "args": {}},
        {"plan": "p", "tool": FINISH, "args": {"answer": "done"}},
    ]
    for action in ok:
        jsonschema.validate(action, schema)

    bad = [
        {"plan": "p", "tool": "rm_rf", "args": {}},                          # unknown tool
        {"plan": "p", "tool": "get_weather", "args": {"city": "Pune"}},      # wrong arg key
        {"plan": "p", "tool": "get_weather", "args": {}},                     # missing required
        {"plan": "p", "tool": "count", "args": {"n": "three"}},               # wrong type
        {"tool": "count", "args": {}},                                        # no reasoning
        {"plan": "x" * 500, "tool": "count", "args": {}},                     # unbounded text
    ]
    for action in bad:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(action, schema)


def test_large_menu_uses_compact_enum_schema():
    tools = [_tool(f"t{i:02d}", _count) for i in range(MAX_PER_TOOL_BRANCHES + 1)]
    schema = build_action_schema(tools)
    assert len(schema["anyOf"]) == 2
    jsonschema.validate({"intent": "i", "tool": "t07", "args": {"x": 1}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"intent": "i", "tool": "nope", "args": {}}, schema)


def test_schema_compiles_to_llama_grammar():
    llama_cpp = pytest.importorskip("llama_cpp")
    schema = build_action_schema([_tool("get_weather", _weather), _tool("count", _count)])
    grammar = llama_cpp.LlamaGrammar.from_json_schema(json.dumps(schema), verbose=False)
    assert grammar is not None


# =============================================================================
# Graph → llm_generate → router plumbing
# =============================================================================


def _graph(llm_generate):
    from src.app.services.agent_loop import AmadeusGraph
    from src.app.services.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_tool("get_weather", _weather))
    return AmadeusGraph(tool_registry=registry, tool_executor=MagicMock(),
                        llm_generate=llm_generate)


@pytest.mark.asyncio
async def test_graph_sends_expert_schema_when_supported():
    seen: list[dict] = []

    async def llm_generate(prompt, **kwargs):
        seen.append(kwargs)
        return '{"plan": "p", "tool": "FINISH", "args": {"answer": "ok"}}'

    graph = _graph(llm_generate)
    profile = graph._profiles["generalist"]
    await graph._generate_action("prompt", profile, lead="plan")
    schema = seen[0]["json_schema"]
    assert seen[0]["structured"] is True
    tool_values = [b["properties"]["tool"] for b in schema["anyOf"]]
    assert {"const": "get_weather"} in tool_values
    assert {"const": FINISH} in tool_values


@pytest.mark.asyncio
async def test_graph_falls_back_for_callables_without_schema_kwarg():
    async def llm_generate(prompt, structured=False):
        return "{}"

    graph = _graph(llm_generate)
    assert graph._llm_accepts_schema is False
    assert await graph._generate_action("p", graph._profiles["generalist"], "plan") == "{}"


@pytest.mark.asyncio
async def test_router_uses_grammar_for_local_structured_calls():
    from src.infra.llm.router import LLMRouter

    llama = MagicMock()
    llama.generate_response = AsyncMock(return_value='{"intent":"i","tool":"FINISH","args":{}}')
    gemini = MagicMock()
    gemini.generate_response = AsyncMock(return_value="cloud")
    router = LLMRouter(llama_cpp=llama, gemini=gemini)
    schema = {"type": "object"}

    _, provider = await router.generate("pick a tool", json_schema=schema)
    assert provider == "llama_cpp"  # no longer skipped: output is grammar-bound
    fmt = llama.generate_response.await_args.kwargs["response_format"]
    assert fmt == {"type": "json_object", "schema": schema}


@pytest.mark.asyncio
async def test_router_still_skips_local_for_unconstrained_structured_calls():
    from src.infra.llm.router import LLMRouter

    llama = MagicMock()
    llama.generate_response = AsyncMock(return_value="{}")
    gemini = MagicMock()
    gemini.generate_response = AsyncMock(return_value="{}")
    router = LLMRouter(llama_cpp=llama, gemini=gemini)

    _, provider = await router.generate("pick a tool", structured=True)
    assert provider == "gemini"
    llama.generate_response.assert_not_called()
