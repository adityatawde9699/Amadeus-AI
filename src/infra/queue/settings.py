import logging
from typing import Any

from arq.connections import RedisSettings

from src.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

async def execute_tool_job(ctx: dict[str, Any], tool_name: str, args: dict[str, Any], context_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Background job to execute slow tools using ToolDispatcher.
    """
    logger.info("Starting background job for tool '%s'", tool_name)

    try:
        # Load necessary dependencies lazily to avoid circular imports in the worker
        from src.app.services.tool_dispatcher import ToolDispatcher
        from src.container import get_cache_service, get_tool_registry
        from src.core.domain.context import RequestContext
        from src.core.domain.models import PermissionProfile
        from src.infra.tools.base import ToolExecutor

        registry = get_tool_registry()
        executor = ToolExecutor()
        cache = get_cache_service()
        dispatcher = ToolDispatcher(tool_registry=registry, tool_executor=executor, cache_service=cache)

        # Deserialize the RequestContext dict back to an object.
        # Fail closed: a job whose payload is missing/blank/invalid `permissions`
        # runs at the least-privilege profile (never SYSTEM_FULL). The enqueuer
        # (QueueManager.enqueue_tool) always serializes the caller's real profile;
        # this default only guards malformed/crafted jobs on the Redis queue.
        raw_permissions = context_dict.get("permissions") or PermissionProfile.READ_ONLY.value
        try:
            permissions = PermissionProfile(raw_permissions)
        except ValueError:
            logger.warning(
                "Background job for '%s' had unknown permissions %r — defaulting to READ_ONLY",
                tool_name,
                raw_permissions,
            )
            permissions = PermissionProfile.READ_ONLY

        request_context = RequestContext(
            request_id=context_dict.get("request_id", ""),
            session_id=context_dict.get("session_id", ""),
            user_id=context_dict.get("user_id", ""),
            permissions=permissions,
            memory_scope=context_dict.get("memory_scope", "global"),
            trace_id=context_dict.get("trace_id"),
        )

        result = await dispatcher.dispatch(tool_name, args, request_context)
        return {
            "success": result.success,
            "output": result.output,
            "error_message": result.error_message,
        }
    except Exception as e:
        logger.exception("Background job execution failed for tool '%s'", tool_name)
        return {
            "success": False,
            "output": f"Job execution failed: {e}",
            "error_message": str(e)
        }

class WorkerSettings:
    """Settings for the Arq worker."""
    functions = [execute_tool_job]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL or "redis://localhost:6379/0")
    max_jobs = 10
    job_timeout = 300
