import asyncio
from dataclasses import dataclass, field

from src.core.domain.models import PermissionProfile


@dataclass
class RequestContext:
    """
    Isolates request context from service singletons, ensuring safe concurrent execution.
    Passed through AmadeusService, AgentOrchestrator, and ToolDispatcher.
    """
    request_id: str
    session_id: str
    user_id: str
    permissions: PermissionProfile
    memory_scope: str = "global"
    trace_id: str | None = None
    cancellation_token: asyncio.Event = field(default_factory=asyncio.Event)
