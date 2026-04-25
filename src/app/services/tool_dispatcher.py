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

from src.core.domain.models import PermissionProfile

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
    ) -> None:
        self._registry = tool_registry
        self._executor = tool_executor
        self._cache = cache_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        tool_name: str,
        args: dict,
        permission_profile: PermissionProfile = PermissionProfile.SYSTEM_FULL,
    ) -> ToolDispatchResult:
        """
        Execute *tool_name* with *args* under the given *permission_profile*.

        Returns a ToolDispatchResult — never propagates exceptions; errors
        are captured into the result instead.
        """
        tool = self._registry.get(tool_name)
        if tool is None:
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
        try:
            result = await asyncio.wait_for(
                self._executor.execute(tool, args, permission_profile=permission_profile),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("Tool '%s' timed out after %ds", tool_name, timeout_s)
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
            return ToolDispatchResult(
                success=True,
                output=output_str,
                tool_name=tool_name,
            )

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
