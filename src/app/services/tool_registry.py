"""
Tool Registry for Amadeus AI Assistant.

Central registry for managing all available tools. Handles registration,
lookup, and filtering of tools by category or name.

Usage:
    from src.app.services.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover_tools()  # Auto-discover from src/infra/tools/

    weather_tool = registry.get("get_weather")
    system_tools = registry.get_by_category("system")
"""

import asyncio
import importlib
import inspect
import logging
import pkgutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.core.domain.models import ToolDefinition
from src.infra.tools.base import Tool, ToolCategory


logger = logging.getLogger(__name__)


def _genai_types() -> tuple[Any, Any] | None:
    """Lazily import Gemini SDK types.

    google.genai costs ~62MB RSS at import — only pay for it when Gemini
    declarations are actually requested (never in LOCAL_ONLY_MODE).
    """
    try:
        from google.genai.types import FunctionDeclaration
        from google.genai.types import Tool as GenAITool

        return FunctionDeclaration, GenAITool
    except ImportError:
        return None


class ToolRegistry:
    """
    Central registry for all Amadeus tools.

    Provides tool discovery, registration, and lookup functionality.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        # Each MCP server runs in its own task that owns the full lifecycle of
        # its anyio context managers (stdio_client + ClientSession). We only
        # ever signal it to stop and await it — we never exit those contexts
        # from another task, which would trip anyio's cancel-scope guard.
        self._mcp_tasks: list[tuple[asyncio.Task[None], asyncio.Event]] = []

    def register(self, tool: Tool) -> None:
        """
        Register a tool with the registry.

        Args:
            tool: The Tool instance to register
        """
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (%s)", tool.name, tool.category.value)

    def register_function(
        self,
        func: Any,
        name: str,
        description: str,
        category: ToolCategory,
        parameters: dict | None = None,
        requires_confirmation: bool = False,
    ) -> None:
        """
        Register a function as a tool.

        Args:
            func: The callable to register
            name: Tool name
            description: Tool description
            category: Tool category
            parameters: Parameter schema
            requires_confirmation: Whether confirmation is needed
        """
        tool = Tool(
            name=name,
            function=func,
            description=description,
            category=category,
            parameters=parameters or {},
            requires_confirmation=requires_confirmation,
        )
        self.register(tool)

    def get(self, name: str) -> Tool | None:
        """
        Get a tool by name.

        Args:
            name: The tool name

        Returns:
            The Tool if found, None otherwise
        """
        return self._tools.get(name)

    def get_by_category(self, category: str | ToolCategory) -> list[Tool]:
        """
        Get all tools in a category.

        Args:
            category: Category name or ToolCategory enum

        Returns:
            List of tools in the category
        """
        cat_str = category.value if isinstance(category, ToolCategory) else str(category)
        return [t for t in self._tools.values() if cat_str in (t.category, t.category.value)]

    def get_by_names(self, names: list[str]) -> list[Tool]:
        """
        Get multiple tools by their names.

        Args:
            names: List of tool names

        Returns:
            List of found tools (skips missing ones)
        """
        return [self._tools[n] for n in names if n in self._tools]

    def list_all(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tools_by_categories(self, categories: list[ToolCategory]) -> list[Tool]:
        """Get all tools belonging to any of the given categories.

        Used by MoE Expert Nodes to retrieve only their permitted tool subset.

        Args:
            categories: List of ToolCategory enums to include

        Returns:
            List of tools whose category matches any of the given categories
        """
        cat_values = {c.value for c in categories}
        return [t for t in self._tools.values() if t.category.value in cat_values]

    def get_tools_menu_for_categories(self, categories: list[ToolCategory]) -> str:
        """Generate a concise text menu of tools limited to specific categories.

        Used by MoE Expert Nodes to build a small, focused tool prompt.
        """
        tools = self.get_tools_by_categories(categories)
        lines = []
        for tool in sorted(tools, key=lambda t: t.name):
            desc = tool.description.split("\n")[0].strip()
            if not desc.endswith("."):
                desc += "."
            lines.append(f"- {tool.name}: {desc}")
        return "\n".join(lines)

    def list_names(self) -> list[str]:
        """Get all tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    # =========================================================================
    # GEMINI INTEGRATION
    # =========================================================================

    def build_gemini_tools(self, tool_names: list[str] | None = None) -> Any:
        """
        Build Gemini function declarations for the specified tools.

        Args:
            tool_names: List of tool names, or None for all tools

        Returns:
            List of function declarations in Gemini format (Tool objects if SDK available)
        """
        tools = self.list_all() if tool_names is None else self.get_by_names(tool_names)

        # If we have the SDK, use its types to be safe
        genai = _genai_types()
        if genai is not None:
            FunctionDeclaration, GenAITool = genai
            declarations = []
            for t in tools:
                # Convert dict to FunctionDeclaration using **kwargs
                # The high-level types usually accept dicts and handle enum conversion
                d = t.to_gemini_declaration()
                try:
                    declarations.append(FunctionDeclaration(**d))
                except Exception as e:
                    logger.warning("Failed to create FunctionDeclaration for %s: %s", t.name, e)
                    # Fallback to raw dict if wrapper fails
                    declarations.append(d)  # type: ignore[arg-type]

            # Return as a list of Tool objects (or FunctionDeclarations which might be auto-wrapped)
            # generate_content(tools=[...]) accepts a list of Tools.
            # We create one Tool containing all these functions.
            try:
                return [GenAITool(function_declarations=declarations)]
            except Exception:
                # If Tool wrapper fails, maybe passed list of Declarations directly?
                return declarations

        # Fallback to pure dict structure
        return [{"function_declarations": [t.to_gemini_declaration() for t in tools]}]

    def build_gemini_declarations_for_category(self, category: ToolCategory) -> Any:
        """Build Gemini declarations for a specific category."""
        tools = self.get_by_category(category)
        genai = _genai_types()
        if genai is not None:
            FunctionDeclaration, GenAITool = genai
            declarations = [FunctionDeclaration(**t.to_gemini_declaration()) for t in tools]
            return [GenAITool(function_declarations=declarations)]

        return [{"function_declarations": [t.to_gemini_declaration() for t in tools]}]

    # =========================================================================
    # TOOL DEFINITIONS (DOMAIN MODELS)
    # =========================================================================

    def get_definitions(self, tool_names: list[str] | None = None) -> list[ToolDefinition]:
        """
        Get ToolDefinition domain models for tools.

        Args:
            tool_names: List of tool names, or None for all

        Returns:
            List of ToolDefinition models
        """
        tools = self.list_all() if tool_names is None else self.get_by_names(tool_names)

        return [t.to_definition() for t in tools]

    # =========================================================================
    # AUTO-DISCOVERY & PLUGINS
    # =========================================================================

    def discover_tools(self, package_name: str = "src.infra.tools") -> int:
        """
        Auto-discover and register tools from a package.

        Looks for functions decorated with @tool in the package.

        Args:
            package_name: The package to scan for tools

        Returns:
            Number of tools discovered
        """
        count = 0

        try:
            package = importlib.import_module(package_name)

            # pkgutil.iter_modules only works if the package has a __path__
            package_path = getattr(package, "__path__", None)
            if not package_path:
                logger.warning("Package %s has no __path__, cannot discover tools", package_name)
                return 0

            for _, module_name, _ in pkgutil.iter_modules(package_path):
                if module_name.startswith("_"):
                    continue  # Skip private modules

                try:
                    module = importlib.import_module(f"{package_name}.{module_name}")

                    # Look for functions with _tool_metadata
                    for name in dir(module):
                        obj = getattr(module, name)
                        if hasattr(obj, "_tool_metadata"):
                            self.register(obj._tool_metadata)
                            count += 1
                        # Support for build_* or get_* functions that return list of Tools
                        elif (name.startswith(("build_", "get_"))) and callable(obj):
                            try:
                                # Only call if it doesn't require arguments or has defaults
                                sig = inspect.signature(obj)
                                if all(p.default != inspect.Parameter.empty for p in sig.parameters.values()):
                                    result = obj()
                                    if isinstance(result, list):
                                        for item in result:
                                            if hasattr(item, "name") and hasattr(item, "function"):
                                                self.register(item)
                                                count += 1
                            except Exception:
                                pass # Skip if it fails (likely requires args)

                except Exception as e:
                    logger.exception("Error loading module %s: %s", module_name, e)

        except Exception as e:
            logger.exception("Error discovering tools from %s: %s", package_name, e)

        logger.info("Discovered %d tools from %s", count, package_name)
        return count

    def discover_plugins(self, plugins_dir: str | Path) -> int:
        """
        Discover and register tools from a plugins directory.

        Each .py file or subdirectory with __init__.py in the directory is treated as a plugin.

        Args:
            plugins_dir: Path to the plugins directory

        Returns:
            Number of tools discovered
        """
        import sys
        from pathlib import Path

        plugins_path = Path(plugins_dir).resolve()
        if not plugins_path.exists():
            logger.warning("Plugins directory %s does not exist", plugins_path)
            return 0

        # Add plugins directory to sys.path so we can import from it
        if str(plugins_path) not in sys.path:
            sys.path.insert(0, str(plugins_path))

        count = 0

        # Scan for .py files or directories with __init__.py
        for path in plugins_path.iterdir():
            if path.name.startswith("_"):
                continue

            module_name = None
            if path.is_file() and path.suffix == ".py":
                module_name = path.stem
            elif path.is_dir() and (path / "__init__.py").exists():
                module_name = path.name

            if module_name:
                try:
                    module = importlib.import_module(module_name)
                    importlib.reload(module) # Ensure fresh load

                    # 1. Check for register_tools(registry) hook
                    if hasattr(module, "register_tools") and callable(module.register_tools):
                        module.register_tools(self)
                        # We don't know exactly how many were registered via the hook
                        # so we'll re-count later or just trust the hook.
                        logger.info("Executed register_tools hook for plugin: %s", module_name)

                    # 2. Look for @tool decorated functions
                    for name in dir(module):
                        obj = getattr(module, name)
                        if hasattr(obj, "_tool_metadata"):
                            self.register(obj._tool_metadata)
                            count += 1

                except Exception as e:
                    logger.exception("Error loading plugin %s: %s", module_name, e)

        logger.info("Discovered %d tools from plugins directory: %s", count, plugins_dir)
        return count

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def get_summary(self) -> dict:
        """Get a summary of registered tools."""
        categories: dict[str, list[str]] = {}
        for tool in self._tools.values():
            cat = tool.category.value
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(tool.name)

        return {
            "total": len(self._tools),
            "categories": categories,
        }

    def get_tools_menu(self) -> str:
        """
        Generate a concise text summary of all tools for the LLM router.
        Format: "- tool_name: description"
        """
        lines = []
        # Sort tools by name for consistent prompts
        sorted_tools = sorted(self._tools.values(), key=lambda t: t.name)
        for tool in sorted_tools:
            # Cleaning description to fit on one line
            desc = tool.description.split("\n")[0].strip()
            if not desc.endswith("."):
                desc += "."
            lines.append(f"- {tool.name}: {desc}")

        return "\n".join(lines)

    # =========================================================================
    # MCP (MODEL CONTEXT PROTOCOL) INTEGRATION
    # =========================================================================

    async def connect_mcp_server(self, command: str, name: str) -> int:
        """
        Connect an MCP server via stdio and register its tools.

        The server's stdio_client/ClientSession context managers are entered and
        exited entirely within a single dedicated task (see ``_run_mcp_server``).
        anyio attaches cancel scopes to those context managers and refuses to let
        them be closed from a different task than the one that opened them — the
        old code entered them here and exited them in ``shutdown_mcp`` (a different
        task), which raised "Attempted to exit cancel scope in a different task".

        Args:
            command: The command to run the MCP server (e.g. "npx @modelcontextprotocol/server-github")
            name: Namespace for the tools (e.g. "github")

        Returns:
            Number of tools registered (0 if the connection failed)
        """
        logger.info("Connecting to MCP server '%s' with command: %s", name, command)

        ready = asyncio.Event()
        shutdown = asyncio.Event()
        result: dict[str, Any] = {"count": 0, "error": None}

        task = asyncio.create_task(
            self._run_mcp_server(command, name, ready, shutdown, result),
            name=f"mcp-{name}",
        )
        self._mcp_tasks.append((task, shutdown))

        # Block until the server is initialized and its tools are registered, or
        # until the lifecycle task fails (it sets `ready` in either case).
        await ready.wait()

        if result["error"]:
            return 0
        return int(result["count"])

    async def _run_mcp_server(
        self,
        command: str,
        name: str,
        ready: asyncio.Event,
        shutdown: asyncio.Event,
        result: dict[str, Any],
    ) -> None:
        """Own an MCP server's full connection lifecycle inside one task.

        Opens the stdio + session context managers, registers the tools, signals
        ``ready``, then parks on ``shutdown`` so the contexts stay open. When
        signalled, the ``AsyncExitStack`` closes them here — in the same task that
        opened them — keeping anyio's structured-concurrency invariants intact.
        """
        import shlex
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            parts = shlex.split(command)
            if not parts:
                result["error"] = f"empty command for MCP server '{name}'"
                logger.error("Empty command for MCP server '%s'", name)
                return

            server_params = StdioServerParameters(command=parts[0], args=parts[1:])

            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(server_params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                tools_result = await session.list_tools()
                count = 0
                for mcp_tool in tools_result.tools:
                    self._register_mcp_tool(session, mcp_tool, server_name=name)
                    count += 1
                result["count"] = count
                logger.info("Registered %d tools from MCP server '%s'", count, name)

                # Unblock connect_mcp_server, then hold the contexts open until
                # shutdown is requested.
                ready.set()
                await shutdown.wait()
        except Exception as e:
            result["error"] = str(e)
            logger.exception("Failed to connect to MCP server '%s': %s", name, e)
        finally:
            # Ensure a stuck/failed startup never leaves connect_mcp_server hung.
            ready.set()

    def _register_mcp_tool(self, session: Any, mcp_tool: Any, server_name: str) -> None:
        """Register a single MCP tool as an Amadeus tool."""

        async def _caller(**kwargs: Any) -> Any:
            try:
                result = await session.call_tool(mcp_tool.name, kwargs)
                # MCP results often have a 'content' field with a list of items
                if hasattr(result, "content") and isinstance(result.content, list):
                    # Combine text content for the LLM
                    return "\n".join([c.text for c in result.content if hasattr(c, "text")])
                return str(result)
            except Exception as e:
                logger.exception("Error calling MCP tool %s.%s: %s", server_name, mcp_tool.name, e)
                return f"Error: {e}"

        # Standardize parameter schema (MCP uses 'inputSchema' or 'input_schema')
        parameters = getattr(mcp_tool, "inputSchema", getattr(mcp_tool, "input_schema", {}))

        tool_name = f"{server_name}_{mcp_tool.name}"

        self.register_function(
            func=_caller,
            name=tool_name,
            description=mcp_tool.description or f"MCP tool: {mcp_tool.name}",
            category=ToolCategory.WEB_RESEARCH,
            parameters=parameters,
        )

    async def shutdown_mcp(self) -> None:
        """Shut down all MCP sessions.

        Signals each lifecycle task to stop and awaits it. Each task closes its
        own context managers (in-task), so we never touch anyio cancel scopes
        from here.
        """
        if not self._mcp_tasks:
            return

        for _, shutdown in self._mcp_tasks:
            shutdown.set()

        results = await asyncio.gather(
            *(task for task, _ in self._mcp_tasks), return_exceptions=True
        )
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Error during MCP shutdown: %s", r)

        self._mcp_tasks.clear()
