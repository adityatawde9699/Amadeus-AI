"""Attributes the agent-graph mixins rely on; set by ``AmadeusGraph.__init__``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.app.services.tool_registry import ToolRegistry
    from src.core.domain.agent_profiles import AgentProfile
    from src.infra.tools.base import ToolExecutor


class GraphBase:
    """Declarations only — lets each mixin type-check on its own."""

    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    llm_generate: Callable[..., Awaitable[str]] | None
    memory_service: Any | None
    default_max_iterations: int
    _llm_accepts_schema: bool
    _profiles: dict[str, AgentProfile]
