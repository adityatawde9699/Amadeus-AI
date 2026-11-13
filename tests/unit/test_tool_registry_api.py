"""ToolRegistry lookups, menus, Gemini declarations and plugin discovery."""

from __future__ import annotations

import textwrap

import pytest

from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory


def _fn_weather(location: str, units: str = "metric", **kwargs) -> str:
    return location


def _fn_add(a: int, b: int) -> int:
    return a + b


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="get_weather",
            function=_fn_weather,
            category=ToolCategory.WEATHER,
            description="Current weather\nsecond line ignored",
            parameters={"location": {"type": "string"}},
        )
    )
    reg.register(
        Tool(
            name="add",
            function=_fn_add,
            category=ToolCategory.CALCULATION,
            description="Add two numbers.",
        )
    )
    return reg


def test_lookups_and_container_protocol(registry):
    assert registry.get("add").name == "add" and registry.get("nope") is None
    assert [t.name for t in registry.get_by_category(ToolCategory.WEATHER)] == ["get_weather"]
    assert [t.name for t in registry.get_by_category("calculation")] == ["add"]
    assert [t.name for t in registry.get_by_names(["add", "missing"])] == ["add"]
    assert len(registry) == 2 and "add" in registry and "x" not in registry
    assert sorted(registry.list_names()) == ["add", "get_weather"]
    assert {t.name for t in registry} == {"add", "get_weather"}
    assert registry.get_summary() == {
        "total": 2,
        "categories": {"weather": ["get_weather"], "calculation": ["add"]},
    }


def test_menus_show_parameter_names(registry):
    menu = registry.get_tools_menu_for_categories([ToolCategory.WEATHER, ToolCategory.CALCULATION])
    assert menu.splitlines() == [
        "- add(a, b): Add two numbers.",
        "- get_weather(location, units?): Current weather.",
    ]
    assert "get_weather" in registry.get_tools_menu()


class _Decl:
    def __init__(self, **kw):
        self.name = kw["name"]


class _GTool:
    def __init__(self, function_declarations):
        self.function_declarations = function_declarations


def test_definitions_and_gemini_declarations(registry, monkeypatch):
    # Other test modules replace google.genai with a MagicMock in sys.modules,
    # so inject the SDK types instead of depending on import order.
    from src.app.services import tool_registry as mod

    monkeypatch.setattr(mod, "_genai_types", lambda: (_Decl, _GTool))
    defs = registry.get_definitions(["get_weather"])
    assert [d.name for d in defs] == ["get_weather"] and len(registry.get_definitions()) == 2
    tools = registry.build_gemini_tools()
    assert len(tools) == 1
    names = {d.name for d in tools[0].function_declarations}
    assert names == {"get_weather", "add"}
    by_cat = registry.build_gemini_declarations_for_category(ToolCategory.CALCULATION)
    assert [d.name for d in by_cat[0].function_declarations] == ["add"]


def test_discovers_builtin_tools():
    reg = ToolRegistry()
    count = reg.discover_tools()
    assert count >= 50 and len(reg) >= 50
    assert reg.get("calculate") is not None
    assert reg.discover_tools("src.infra.tools.base") == 0  # a module, not a package


def test_discover_plugins(tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    suffix = tmp_path.name.replace("-", "_")
    (plugins / f"decorated_{suffix}.py").write_text(
        textwrap.dedent("""
        from src.infra.tools.base import ToolCategory, tool

        @tool(name="plugin_echo", description="Echo.", category=ToolCategory.SYSTEM)
        def plugin_echo(text: str) -> str:
            return text
    """)
    )
    (plugins / f"hooked_{suffix}.py").write_text(
        textwrap.dedent("""
        from src.infra.tools.base import Tool, ToolCategory

        def register_tools(registry):
            registry.register(Tool(name="plugin_hooked", function=lambda: "ok",
                                   description="Hooked.", category=ToolCategory.SYSTEM))
    """)
    )
    (plugins / f"broken_{suffix}.py").write_text("def oops(:\n")
    (plugins / "_private.py").write_text("raise SystemExit('must not be imported')\n")
    pkg = plugins / f"pkg_{suffix}"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    reg = ToolRegistry()
    assert reg.discover_plugins(plugins) == 1  # decorated tools are counted
    assert "plugin_echo" in reg and "plugin_hooked" in reg
    assert reg.discover_plugins(tmp_path / "missing") == 0
