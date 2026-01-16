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

import importlib
import logging
import pkgutil
from typing import Iterator

from src.core.domain.models import ToolDefinition
from src.infra.tools.base import Tool, ToolCategory


logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for all Amadeus tools.
    
    Provides tool discovery, registration, and lookup functionality.
    """
    
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """
        Register a tool with the registry.
        
        Args:
            tool: The Tool instance to register
        """
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} ({tool.category.value})")
    
    def register_function(
        self,
        func,
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
        if isinstance(category, str):
            category = ToolCategory(category)
        return [t for t in self._tools.values() if t.category == category]
    
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
    
    def build_gemini_tools(self, tool_names: list[str] | None = None) -> list[dict]:
        """
        Build Gemini function declarations for the specified tools.
        
        Args:
            tool_names: List of tool names, or None for all tools
            
        Returns:
            List of function declarations in Gemini format
        """
        if tool_names is None:
            tools = self.list_all()
        else:
            tools = self.get_by_names(tool_names)
        
        return [{"function_declarations": [t.to_gemini_declaration() for t in tools]}]
    
    def build_gemini_declarations_for_category(self, category: ToolCategory) -> list[dict]:
        """Build Gemini declarations for a specific category."""
        tools = self.get_by_category(category)
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
        if tool_names is None:
            tools = self.list_all()
        else:
            tools = self.get_by_names(tool_names)
        
        return [t.to_definition() for t in tools]
    
    # =========================================================================
    # AUTO-DISCOVERY
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
            
            for _, module_name, _ in pkgutil.iter_modules(package.__path__):
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
                            
                except Exception as e:
                    logger.error(f"Error loading module {module_name}: {e}")
                    
        except Exception as e:
            logger.error(f"Error discovering tools from {package_name}: {e}")
        
        logger.info(f"Discovered {count} tools from {package_name}")
        return count
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    
    def get_summary(self) -> dict:
        """Get a summary of registered tools."""
        categories = {}
        for tool in self._tools.values():
            cat = tool.category.value
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(tool.name)
        
        return {
            "total": len(self._tools),
            "categories": categories,
        }
