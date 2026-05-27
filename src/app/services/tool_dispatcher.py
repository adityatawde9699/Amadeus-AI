"""
Tool Dispatcher for Amadeus AI.

Executes registered tools with per-tool timeouts and optional result caching.
Returns a typed ToolDispatchResult — never raises on tool failure.

Extracted from AmadeusService to comply with Single Responsibility Principle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from opentelemetry import trace
from src.runtime.events import EventBus

if TYPE_CHECKING:
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.cache.cache_service import CacheService
    from src.infra.tools.base import ToolExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ToolDispatchResult:
    """Outcome of a single tool dispatch attempt."""

    success: bool
    output: str
    tool_name: str
    timed_out: bool = False
    error_message: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class ToolDispatcher:
    """
    Looks up, executes, and optionally caches the result of a registered tool.

    Per-tool timeouts prevent long-running operations (e.g. Docker sandbox,
    external APIs) from blocking the event loop indefinitely.
    """

    # Per-tool execution timeout in seconds.
    # Tools not listed here fall back to DEFAULT_TIMEOUT.
    TOOL_TIMEOUTS: ClassVar[dict[str, int]] = {
        "execute_python_script": 300,   # Docker sandbox
        "web_search":            30,
        "get_weather":           20,
        "get_news":              20,
        "wikipedia_search":      20,
        "send_email":            30,
        "read_unread_emails":    30,
        "create_excel_spreadsheet": 60,
        "create_word_document":  60,
    }
    DEFAULT_TIMEOUT: ClassVar[int] = 15

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        cache_service: CacheService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = tool_registry
        self._executor = tool_executor
        self._cache = cache_service
        self.event_bus = event_bus

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        tool_name: str,
        args: dict,
        context: RequestContext,
    ) -> ToolDispatchResult:
        """
        Execute *tool_name* with *args* under the given *context*.

        Returns a ToolDispatchResult — never propagates exceptions; errors
        are captured into the result instead.
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("ToolDispatcher.dispatch") as span:
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("context.session_id", context.session_id)
            
            tool = self._registry.get(tool_name)
            if tool is None:
                span.set_attribute("tool.success", False)
                return ToolDispatchResult(
                    success=False,
                    output=f"Tool '{tool_name}' not found in registry.",
                    tool_name=tool_name,
                    error_message="not_found",
                )
    
            # ── Cache read ────────────────────────────────────────────────
            if self._cache:
                cached = await self._cache.get_tool_result(tool_name, args)
                if cached:
                    logger.debug("Tool cache hit for '%s'", tool_name)
                    self._bump_cache_metric()
                    span.set_attribute("tool.cache_hit", True)
                    span.set_attribute("tool.success", True)
                    return ToolDispatchResult(
                        success=True,
                        output=cached,
                        tool_name=tool_name,
                        extra={"cache_hit": True},
                    )
    
            # ── Increment Prometheus counter ──────────────────────────────
            self._bump_tool_metric(tool_name)
    
            # ── Execute with per-tool timeout ─────────────────────────────
            timeout_s = self.TOOL_TIMEOUTS.get(tool_name, self.DEFAULT_TIMEOUT)
            
            # Enqueue slow tools via arq if applicable (placeholder for 1.3 integration)
            # TODO: integrate with arq Redis queue for background execution.
    
            try:
                result = await asyncio.wait_for(
                    self._executor.execute(tool, args, permission_profile=context.permissions),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("Tool '%s' timed out after %ds", tool_name, timeout_s)
                span.set_attribute("tool.timeout", True)
                span.set_attribute("tool.success", False)
                return ToolDispatchResult(
                    success=False,
                    output=(
                        f"The {tool_name} tool took too long to respond ({timeout_s}s). "
                        "Please try again or simplify your request."
                    ),
                    tool_name=tool_name,
                    timed_out=True,
                )

            if result.success:
                output_str = str(result.result)
                # ── Cache write ───────────────────────────────────────────
                if self._cache:
                    await self._cache.set_tool_result(tool_name, args, output_str)
                span.set_attribute("tool.success", True)
                
                if self.event_bus:
                    await self.event_bus.emit("tool.completed", {"tool_name": tool_name})
                    
                return ToolDispatchResult(
                    success=True,
                    output=output_str,
                    tool_name=tool_name,
                )
    
            span.set_attribute("tool.success", False)
            if result.error_message:
                span.set_attribute("tool.error", result.error_message)
                
            if self.event_bus:
                await self.event_bus.emit("tool.failed", {"tool_name": tool_name, "error": result.error_message})
                
            return ToolDispatchResult(
                success=False,
                output=f"I tried to use {tool_name} but encountered an issue: {result.error_message}",
                tool_name=tool_name,
                error_message=result.error_message,
            )

    # ------------------------------------------------------------------
    # Metrics helpers (best-effort — never raise)
    # ------------------------------------------------------------------

    @staticmethod
    def _bump_tool_metric(tool_name: str) -> None:
        try:
            from src.infra.metrics import amadeus_tool_calls_total
            amadeus_tool_calls_total.labels(tool_name=tool_name).inc()
        except Exception:
            pass

    def _bump_cache_metric(self) -> None:
        try:
            from src.infra.metrics import amadeus_cache_hit_rate
            if self._cache:
                stats = self._cache.get_stats()
                amadeus_cache_hit_rate.set(stats["hit_rate_pct"])
        except Exception:
            pass
