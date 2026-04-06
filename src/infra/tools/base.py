"""
Tool base infrastructure for Amadeus AI Assistant.

This module provides the base classes, decorators, and utilities for
defining and managing tools in a consistent way.

Usage:
    from src.infra.tools.base import tool, ToolCategory

    @tool(
        name="get_weather",
        description="Get current weather for a location",
        category=ToolCategory.INFORMATION,
        parameters={"location": {"type": "string", "description": "City name"}}
    )
    async def get_weather(location: str) -> str:
        ...
"""

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast


if TYPE_CHECKING:
    from src.infra.tools.confirmation import ConfirmationCallback

from src.core.domain.models import PermissionProfile, ToolDefinition, ToolExecutionResult


logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# TOOL CATEGORIES
# =============================================================================

class ToolCategory(StrEnum):
    """Categories for organizing tools."""
    SYSTEM = "system"           # Hardware, OS, files
    INFORMATION = "information"  # Web, search, calculations
    PRODUCTIVITY = "productivity"  # Tasks, notes, reminders, calendar
    COMMUNICATION = "communication"  # Future: email, messaging


# =============================================================================
# TOOL DATACLASS
# =============================================================================

@dataclass
class Tool:
    """
    Enhanced tool definition with metadata and execution support.

    Attributes:
        name: Unique identifier for the tool
        function: The callable to execute
        description: Human-readable description for LLM
        category: Tool category for organization
        parameters: Parameter schema for LLM function calling
        requires_confirmation: Whether to ask user before executing
        is_async: Auto-detected from function signature
    """
    name: str
    function: Callable
    description: str
    category: ToolCategory
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    is_async: bool = False

    def get_preview(self, args: dict[str, Any]) -> str:
        """
        Generate a human-readable preview of what this tool will do.
        Overridden by specific tools for better detail.
        """
        params = ", ".join(f"{k}={v}" for k, v in args.items())
        return f"Execute {self.name}({params})"


    def __post_init__(self) -> None:
        """Auto-detect if function is async."""
        self.is_async = asyncio.iscoroutinefunction(self.function)

    def to_definition(self) -> ToolDefinition:
        """Convert to domain ToolDefinition model."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            category=self.category.value,
            parameters=self.parameters,
            requires_confirmation=self.requires_confirmation,
            is_async=self.is_async,
        )

    def to_gemini_declaration(self) -> dict:
        """
        Convert to Gemini function declaration format.

        Returns:
            Dict in format expected by google.generativeai
        """
        # Build parameter properties
        properties = {}
        required = []

        for param_name, param_info in self.parameters.items():
            if isinstance(param_info, dict):
                # FIXED: Capitalize type for Gemini SDK (string -> STRING)
                p_type = param_info.get("type", "string").upper()

                properties[param_name] = {
                    "type": p_type,
                    "description": param_info.get("description", ""),
                }
                if param_info.get("required", True):
                    required.append(param_name)
            else:
                # Simple type string like 'str', 'int'
                type_map = {
                    "str": "STRING",
                    "int": "INTEGER",
                    "float": "NUMBER",
                    "bool": "BOOLEAN"
                }
                properties[param_name] = {
                    "type": type_map.get(param_info, "STRING"),
                }
                required.append(param_name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",  # FIXED: Capitalized
                "properties": properties,
                "required": required,
            } if properties else {"type": "OBJECT", "properties": {}},
        }


# =============================================================================
# TOOL DECORATOR
# =============================================================================

def tool(
    name: str,
    description: str,
    category: ToolCategory,
    parameters: dict | None = None,
    requires_confirmation: bool = False,
) -> Callable[[F], F]:
    """
    Decorator to register a function as a tool.

    Usage:
        @tool(
            name="get_weather",
            description="Get weather for a location",
            category=ToolCategory.INFORMATION,
            parameters={"location": {"type": "string", "description": "City"}}
        )
        async def get_weather(location: str) -> str:
            ...

    Args:
        name: Unique tool name
        description: Description for LLM
        category: Tool category
        parameters: Parameter schema dict
        requires_confirmation: Whether to confirm before executing

    Returns:
        Decorated function with _tool_metadata attribute
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        # Choose wrapper based on async
        final_func: Any = async_wrapper if asyncio.iscoroutinefunction(func) else wrapper

        # Attach metadata as a runtime attribute (cast tells mypy to treat it as F)
        final_func._tool_metadata = Tool(
            name=name,
            function=func,  # Store original function
            description=description,
            category=category,
            parameters=parameters or {},
            requires_confirmation=requires_confirmation,
        )

        return cast(F, final_func)

    return decorator


# =============================================================================
# TOOL EXECUTOR
# =============================================================================

class ToolExecutor:
    """
    Handles safe execution of tools with error handling and retries.

    Parameters
    ----------
    max_retries:
        Number of retry attempts for transient errors.
    retry_delay:
        Seconds to wait between retry attempts.
    confirmation_callback:
        HITL gate invoked before any tool that has ``requires_confirmation=True``.
        If ``None`` and a destructive tool is called, execution is **denied by
        default** (fail-safe behaviour).
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        confirmation_callback: "ConfirmationCallback | None" = None,
    ) -> None:
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.confirmation_callback = confirmation_callback
        self.execution_history: list[dict] = []

    async def execute(
        self,
        tool: Tool,
        args: dict[str, Any],
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> ToolExecutionResult:
        """
        Execute a tool with proper error handling and async support.

        Args:
            tool: The tool to execute
            args: Arguments to pass to the tool function
            permission_profile: The security profile of the requesting user

        Returns:
            ToolExecutionResult with success status and result/error
        """
        start_time = datetime.now()

        # ------------------------------------------------------------------
        # HARD SECURITY GATE
        # READ_ONLY profiles cannot execute destructive actions under any circumstances.
        # ------------------------------------------------------------------
        if permission_profile == PermissionProfile.READ_ONLY and tool.requires_confirmation:
            logger.warning(
                "Execution hard-denied: Profile READ_ONLY blocked destructive tool '%s'",
                tool.name,
            )
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                error_message=(
                    f"Action blocked: Your READ_ONLY permission profile restricts "
                    f"access to the destructive tool '{tool.name}'."
                ),
                execution_time_ms=0.0,
            )

        # ------------------------------------------------------------------
        # HUMAN-IN-THE-LOOP GATE
        # Check requires_confirmation BEFORE any retry loop so we only ask
        # the user once, not once per retry attempt.
        # ------------------------------------------------------------------
        if tool.requires_confirmation:
            from src.infra.tools.confirmation import make_request_id
            request_id = make_request_id()

            if self.confirmation_callback is None:
                # Fail-safe: no callback configured → deny by default
                logger.warning(
                    "confirmation_callback_not_set — denying destructive tool '%s' by default",
                    tool.name,
                )
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    error_message=(
                        f"Tool '{tool.name}' requires user confirmation but no "
                        "confirmation handler is configured. Execution denied."
                    ),
                    execution_time_ms=0.0,
                )

            preview = tool.get_preview(args)
            approved = await self.confirmation_callback.request_approval(
                tool_name=tool.name,
                args=args,
                request_id=request_id,
                preview=preview,
            )
            if not approved:
                logger.info("Tool '%s' execution denied by user (request_id=%s)", tool.name, request_id)
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    error_message=f"User denied execution of '{tool.name}'.",
                    execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                )


        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"Executing tool '{tool.name}' with args: {args} (attempt {attempt + 1})")

                # Validate arguments against expected parameters
                validated_args = self._validate_args(tool, args)

                # Execute based on async or sync
                if tool.is_async:
                    result = await tool.function(**validated_args)
                else:
                    # Run sync functions in executor to not block
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        partial(tool.function, **validated_args)
                    )

                # Calculate execution time
                execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                # Log successful execution
                self.execution_history.append({
                    "tool": tool.name,
                    "args": args,
                    "success": True,
                    "timestamp": datetime.now().isoformat(),
                })

                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                )

            except TypeError as e:
                logger.warning(f"Argument error for {tool.name}: {e}")
                if attempt == self.max_retries:
                    return ToolExecutionResult(
                        tool_name=tool.name,
                        success=False,
                        error_message=f"Invalid arguments for {tool.name}: {e}",
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    )

            except Exception as e:
                logger.error(f"Tool execution error ({tool.name}): {e}", exc_info=True)
                if attempt == self.max_retries:
                    self.execution_history.append({
                        "tool": tool.name,
                        "args": args,
                        "success": False,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                    })
                    return ToolExecutionResult(
                        tool_name=tool.name,
                        success=False,
                        error_message=f"Error executing {tool.name}: {e}",
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    )
                await asyncio.sleep(self.retry_delay)

        return ToolExecutionResult(
            tool_name=tool.name,
            success=False,
            error_message="Max retries exceeded",
            execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
        )

    def _validate_args(self, tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and clean arguments for a tool."""
        sig = inspect.signature(tool.function)
        valid_params = set(sig.parameters.keys())

        # Filter to only valid parameters
        cleaned = {k: v for k, v in args.items() if k in valid_params}

        # Check for required parameters
        for name, param in sig.parameters.items():
            if param.default == inspect.Parameter.empty and name not in cleaned:
                if name not in ("self", "cls"):
                    logger.warning(f"Missing required parameter '{name}' for {tool.name}")

        return cleaned

    def get_recent_executions(self, limit: int = 10) -> list[dict]:
        """Get recent execution history."""
        return self.execution_history[-limit:]

    def clear_history(self) -> None:
        """Clear execution history."""
        self.execution_history.clear()
