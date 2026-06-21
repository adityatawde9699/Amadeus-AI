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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast


if TYPE_CHECKING:
    from src.infra.tools.confirmation import ConfirmationCallback

from src.core.domain.models import PermissionProfile, ToolDefinition, ToolExecutionResult
from src.infra.tools.policy import ToolPolicyEngine, ToolPolicyViolation


logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# TOOL CATEGORIES
# =============================================================================


class ToolCategory(StrEnum):
    """Fine-grained categories for tool routing precision.

    These are used by both the SVM category pre-filter and the sentence
    transformer cosine-similarity stage to narrow the candidate tool pool.
    """

    # --- OS / Hardware ---
    APP_CONTROL = "app_control"    # open_program, terminate_program, list_open_apps
    FILE_SYSTEM = "file_system"    # search_file, copy_file, move_file, delete_file, create_folder
    OS_CONTROL  = "os_control"     # set_volume, get_volume, set_brightness, take_screenshot
    MONITORING  = "monitoring"     # cpu/memory/disk/battery/network health, uptime, temps

    # --- Information ---
    WEB_RESEARCH = "web_research"  # wikipedia_search, open_website, web_search
    NEWS         = "news"          # get_news
    WEATHER      = "weather"       # get_weather
    CALCULATION  = "calculation"   # calculate, convert_*, convert_currency
    DATETIME     = "datetime"      # get_datetime_info, get_greeting

    # --- Specialist domains ---
    DEVELOPER = "developer"        # execute_python_script, terminal_cmd, search_workspace
    FINANCE   = "finance"          # get_stock_price, get_crypto_price

    # --- Productivity / Personal ---
    TASK_MANAGER  = "task_manager"  # add/list/complete_task, notes, reminders, pomodoro
    COMMUNICATION = "communication" # email, slack

    # --- Agent Internal ---
    PRODUCTIVITY = "productivity"   # store_core_memory, forget_core_memory, schedule_future_task

    # -----------------------------------------------------------------------
    # LEGACY ALIASES — kept so existing code that references the old broad
    # names (SYSTEM, INFORMATION) does not crash before it is migrated.
    # -----------------------------------------------------------------------
    SYSTEM      = "monitoring"
    INFORMATION = "web_research"
    RESEARCH    = "web_research"


# =============================================================================
# TOOL CAPABILITY
# =============================================================================

@dataclass
class ToolCapability:
    name: str
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    timeout_seconds: int = 15
    resource_cost: Literal["trivial", "low", "medium", "high"] = "trivial"
    requires_confirmation: bool = False
    requires_network: bool = False
    modifies_filesystem: bool = False
    modifies_system_state: bool = False
    sandbox_required: bool = False
    # Minimum permission profile required to run this tool. Enforced by the
    # ToolPolicyEngine. Stored as the profile string value ("read_only" |
    # "standard" | "system_full") to avoid an import cycle with domain models.
    min_permission: str = "read_only"
    # False when the capability was auto-derived (no explicit metadata supplied
    # to the @tool decorator). Used by STRICT_TOOL_METADATA enforcement.
    explicit: bool = True


# =============================================================================
# TOOL DATACLASS
# =============================================================================


@dataclass
class Tool:
    """
    Enhanced tool definition with metadata and execution support.
    """

    name: str
    function: Callable
    description: str
    category: ToolCategory
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    capability: ToolCapability | None = None
    is_async: bool = False

    def get_preview(self, args: dict[str, Any]) -> str:
        """
        Generate a human-readable preview of what this tool will do.
        Overridden by specific tools for better detail.
        """
        params = ", ".join(f"{k}={v}" for k, v in args.items())
        return f"Execute {self.name}({params})"

    def __post_init__(self) -> None:
        """Auto-detect if function is async and standardize parameter schemas."""
        self.is_async = inspect.iscoroutinefunction(self.function)

        # Ensure parameters are always wrapped in a standard JSON Schema root
        # If the tool author just provided a properties dict, wrap it.
        if self.parameters and self.parameters.get("type") != "object":
            self.parameters = {
                "type": "object",
                "properties": self.parameters
            }

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

        raw_props = self.parameters.get("properties", {}) if self.parameters else {}

        for param_name, param_info in raw_props.items():
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
                type_map = {"str": "STRING", "int": "INTEGER", "float": "NUMBER", "bool": "BOOLEAN"}
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
            }
            if properties
            else {"type": "OBJECT", "properties": {}},
        }


# =============================================================================
# TOOL DECORATOR
# =============================================================================


# Categories whose tools are privileged enough to demand SYSTEM_FULL by default.
_SYSTEM_FULL_CATEGORIES = {
    ToolCategory.OS_CONTROL,
    ToolCategory.APP_CONTROL,
    ToolCategory.DEVELOPER,
}
# Categories that need STANDARD (everyday productivity / comms / file ops).
_STANDARD_CATEGORIES = {
    ToolCategory.FILE_SYSTEM,
    ToolCategory.TASK_MANAGER,
    ToolCategory.COMMUNICATION,
    ToolCategory.PRODUCTIVITY,
}


def derive_min_permission(category: ToolCategory, requires_confirmation: bool) -> str:
    """Pick a safe default minimum permission for a tool lacking explicit metadata.

    Confirmation-gated (destructive) tools and host/dev/app-control tools require
    SYSTEM_FULL; everyday productivity/file/comms tools require STANDARD; the rest
    (info, monitoring, finance, news, research, weather, calculation) are
    read-only.
    """
    if requires_confirmation or category in _SYSTEM_FULL_CATEGORIES:
        return "system_full"
    if category in _STANDARD_CATEGORIES:
        return "standard"
    return "read_only"


def tool(
    name: str,
    description: str,
    category: ToolCategory,
    parameters: dict | None = None,
    requires_confirmation: bool = False,
    capability: ToolCapability | None = None,
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
        capability: Security and capability policies for this tool

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
        final_func: Any = async_wrapper if inspect.iscoroutinefunction(func) else wrapper

        # Auto-derive a safe capability (with min_permission) when none is given.
        # explicit=False marks it as derived so STRICT_TOOL_METADATA can flag it.
        derived_capability = capability or ToolCapability(
            name=name,
            requires_confirmation=requires_confirmation,
            min_permission=derive_min_permission(category, requires_confirmation),
            explicit=False,
        )

        # Attach metadata as a runtime attribute (cast tells mypy to treat it as F)
        final_func._tool_metadata = Tool(
            name=name,
            function=func,  # Store original function
            description=description,
            category=category,
            parameters=parameters or {},
            requires_confirmation=requires_confirmation,
            capability=derived_capability,
        )

        return cast("F", final_func)

    return decorator


# =============================================================================
# TOOL EXECUTOR
# =============================================================================


class ToolExecutor:
    """
    Handles safe execution of tools with error handling and retries.
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
        # Per-session confirmation callbacks. Resolving the callback by the
        # executing context's session id (instead of mutating a shared attribute)
        # prevents one request from using another's approval channel.
        self._scoped_callbacks: dict[str, ConfirmationCallback] = {}
        # CQ-04: Bounded deque prevents unbounded memory growth in long-running daemons.

        self.execution_history: deque[dict] = deque(maxlen=500)

        # Policy engine to enforce execution bounds
        from src.core.config import get_settings
        _settings = get_settings()
        self.policy_engine = ToolPolicyEngine(
            is_development_mode=getattr(_settings, "ENV", "production") == "development",
            strict_metadata=getattr(_settings, "STRICT_TOOL_METADATA", False),
        )

    def register_confirmation_callback(
        self, session_id: str, callback: "ConfirmationCallback"
    ) -> None:
        """Register a request-scoped confirmation callback for a session."""
        if session_id:
            self._scoped_callbacks[session_id] = callback

    def unregister_confirmation_callback(self, session_id: str) -> None:
        """Remove a previously registered per-session confirmation callback."""
        self._scoped_callbacks.pop(session_id, None)

    def _resolve_confirmation_callback(
        self,
        override: "ConfirmationCallback | None",
        session_id: str | None,
    ) -> "ConfirmationCallback | None":
        """Pick the callback: explicit override > session-scoped > global default."""
        if override is not None:
            return override
        if session_id and session_id in self._scoped_callbacks:
            return self._scoped_callbacks[session_id]
        return self.confirmation_callback

    async def execute(
        self,
        tool: Tool,
        args: dict[str, Any],
        *,
        permission_profile: PermissionProfile | None = None,
        context: "Any | None" = None,
        session_id: str | None = None,
        confirmation_callback: "ConfirmationCallback | None" = None,
    ) -> ToolExecutionResult:
        """
        Execute a tool with proper error handling and async support.

        Args:
            tool: The tool to execute.
            args: Arguments to pass to the tool function.
            permission_profile: Explicit security profile of the requesting user.
            context: The full RequestContext; its ``permissions``/``session_id``
                take precedence when provided.
            session_id: Session id used to resolve a per-session confirmation
                callback (falls back to ``context.session_id``).
            confirmation_callback: Optional per-call override of the confirmation
                channel.

        SECURITY: there is no implicit full-access default. When neither a
        context nor a permission_profile is supplied, the least-privileged
        READ_ONLY profile is used (fail safe).

        Returns:
            ToolExecutionResult with success status and result/error.
        """
        start_time = datetime.now()

        # Resolve effective permission profile (fail safe to READ_ONLY).
        if context is not None and getattr(context, "permissions", None) is not None:
            permission_profile = context.permissions
        if permission_profile is None:
            permission_profile = PermissionProfile.READ_ONLY

        # Resolve the session used for scoped confirmation callbacks.
        effective_session = session_id or getattr(context, "session_id", None)
        active_callback = self._resolve_confirmation_callback(
            confirmation_callback, effective_session
        )

        # ------------------------------------------------------------------
        # NEW: TOOL POLICY ENGINE GATE
        # ------------------------------------------------------------------
        try:
            import uuid

            from src.core.domain.context import RequestContext
            # Use the supplied context when available; otherwise synthesize a
            # minimal one carrying the resolved (least-privilege) profile.
            eval_ctx = context if context is not None else RequestContext(
                request_id=str(uuid.uuid4()),
                session_id=effective_session or "executor",
                user_id="executor",
                permissions=permission_profile,
            )
            self.policy_engine.evaluate(tool, args, eval_ctx)
        except ToolPolicyViolation as e:
            logger.warning("Tool Policy Violation for %s: %s", tool.name, e)
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                error_message=f"Execution denied by security policy: {e}",
                execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
            )

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

            if active_callback is None:
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
            approved = await active_callback.request_approval(
                tool_name=tool.name,
                args=args,
                request_id=request_id,
                preview=preview,
            )
            if not approved:
                logger.info(
                    "Tool '%s' execution denied by user (request_id=%s)", tool.name, request_id
                )
                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=False,
                    error_message=f"User denied execution of '{tool.name}'.",
                    execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                )

        # CQ-03: Surface validation errors immediately, before any retry attempt.
        _probe = self._validate_args(tool, args)
        if "_validation_error" in _probe:
            return ToolExecutionResult(
                tool_name=tool.name,
                success=False,
                error_message=_probe["_validation_error"],
                execution_time_ms=0.0,
            )

        for attempt in range(self.max_retries + 1):
            try:
                logger.info(
                    "Executing tool '%s' with args: %s (attempt %d)",
                    tool.name,
                    args,
                    attempt + 1,
                )

                # Validate arguments against expected parameters
                validated_args = self._validate_args(tool, args)

                # Execute based on async or sync
                if tool.is_async:
                    result = await tool.function(**validated_args)
                else:
                    # Run sync functions in executor to not block
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, partial(tool.function, **validated_args)
                    )

                # Calculate execution time
                execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                # Log successful execution
                self.execution_history.append(
                    {
                        "tool": tool.name,
                        "args": args,
                        "success": True,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                return ToolExecutionResult(
                    tool_name=tool.name,
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                )

            except TypeError as e:
                logger.warning("Argument error for %s: %s", tool.name, e)
                if attempt == self.max_retries:
                    return ToolExecutionResult(
                        tool_name=tool.name,
                        success=False,
                        error_message=f"Invalid arguments for {tool.name}: {e}",
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    )

            except Exception as e:
                logger.error("Tool execution error (%s): %s", tool.name, e, exc_info=True)
                if attempt == self.max_retries:
                    self.execution_history.append(
                        {
                            "tool": tool.name,
                            "args": args,
                            "success": False,
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                    try:
                        from src.infra.metrics import (
                            amadeus_tool_duration_seconds,
                            amadeus_tool_executions_total,
                        )
                        exec_ms = (datetime.now() - start_time).total_seconds() * 1000
                        amadeus_tool_duration_seconds.labels(
                            tool_name=tool.name, success="false"
                        ).observe(exec_ms / 1000)
                        amadeus_tool_executions_total.labels(
                            tool_name=tool.name, result="failure"
                        ).inc()
                    except Exception:
                        pass
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
        """Validate, coerce types, and clean arguments for a tool.

        CQ-03: Embeds a '_validation_error' key when required parameters are
        missing. execute() checks for this sentinel and returns a
        ToolExecutionResult(success=False) so the caller sees a clear error
        instead of a cryptic TypeError from inside the tool function.

        Type coercion: LLMs often return numeric arguments as strings
        (e.g. ``limit: "5"``). We inspect the function signature's annotation
        and coerce ``str → int | float | bool`` so tools that expect a Python
        int do not crash with an AssertionError or TypeError at call time.
        """
        sig = inspect.signature(tool.function)
        valid_params = set(sig.parameters.keys())

        # Filter to only valid parameters
        cleaned = {k: v for k, v in args.items() if k in valid_params}

        # ── Type coercion pass ────────────────────────────────────────────────
        # LLMs frequently return numbers as strings.  Cast them to the
        # annotated type so tools receive the correct Python type.
        for param_name, param in sig.parameters.items():
            if param_name not in cleaned:
                continue
            value = cleaned[param_name]
            annotation = param.annotation
            if annotation is inspect.Parameter.empty or not isinstance(value, str):
                continue
            try:
                if annotation is int or annotation == "int":
                    cleaned[param_name] = int(value)
                elif annotation is float or annotation == "float":
                    cleaned[param_name] = float(value)
                elif annotation is bool or annotation == "bool":
                    cleaned[param_name] = value.lower() not in ("false", "0", "no", "")
            except (ValueError, TypeError):
                # Leave the value as-is; the tool will surface the error itself
                logger.debug(
                    "_validate_args: could not coerce '%s'=%r to %s for tool '%s'",
                    param_name, value, annotation, tool.name,
                )

        # Check for required parameters
        # Exclude VAR_KEYWORD (**kwargs) and VAR_POSITIONAL (*args) — they are
        # never "missing" in the traditional sense and have no default value,
        # which caused them to be incorrectly flagged as required parameters.
        _SKIP_KINDS = (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        missing = []
        for name, param in sig.parameters.items():
            if (
                param.kind in _SKIP_KINDS
                or name in ("self", "cls")
            ):
                continue
            if (
                param.default == inspect.Parameter.empty
                and name not in cleaned
            ):
                missing.append(name)

        if missing:
            logger.warning(
                "Missing required parameter(s) for %s: %s", tool.name, ", ".join(missing)
            )
            cleaned["_validation_error"] = "Missing required parameter(s): {}".format(
                ", ".join(missing)
            )

        return cleaned

    def get_recent_executions(self, limit: int = 10) -> list[dict]:
        """Get recent execution history."""
        return list(self.execution_history)[-limit:]

    def clear_history(self) -> None:
        """Clear execution history."""
        self.execution_history.clear()
