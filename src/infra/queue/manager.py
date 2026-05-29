"""
Task Queue Manager for Amadeus AI.

Handles enqueuing background jobs using ARQ.
"""

import logging
from typing import Any
from arq import create_pool
from arq.connections import RedisSettings
from src.core.config import get_settings
from src.core.domain.context import RequestContext

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Manages background job enqueuing for Amadeus.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._settings = get_settings()
        self._redis_url = redis_url or self._settings.REDIS_URL
        self._pool = None

    async def initialize(self) -> None:
        """Initialize the Redis pool for enqueuing jobs."""
        if self._pool is None:
            redis_settings = RedisSettings.from_dsn(self._redis_url)
            self._pool = await create_pool(redis_settings)
            logger.info("QueueManager: Connected to Redis for background jobs.")

    async def enqueue_tool(self, tool_name: str, args: dict[str, Any], context: RequestContext) -> str:
        """
        Enqueue a tool execution job.
        
        Returns:
            The job ID.
        """
        if self._pool is None:
            await self.initialize()
            
        # Serialize RequestContext for the job
        context_dict = {
            "request_id": context.request_id,
            "session_id": context.session_id,
            "user_id": context.user_id,
            "permissions": context.permissions.value if hasattr(context.permissions, "value") else str(context.permissions),
            "memory_scope": context.memory_scope,
            "trace_id": context.trace_id,
        }
        
        job = await self._pool.enqueue_job("execute_tool_job", tool_name, args, context_dict)
        logger.info("Enqueued background job %s for tool '%s'", job.job_id, tool_name)
        return job.job_id

    async def get_job_result(self, job_id: str) -> Any:
        """Get the result of a background job."""
        if self._pool is None:
            await self.initialize()
            
        job = self._pool.get_job(job_id)
        return await job.result()

    async def close(self) -> None:
        """Close the Redis pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
