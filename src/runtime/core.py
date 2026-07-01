import asyncio
import logging
from typing import Any

from src.core.config import Settings
from src.core.domain.context import RequestContext
from src.infra.resilience.watchdog import DependencyWatchdog
from src.runtime.cognitive.core import CognitiveCore
from src.runtime.events import EventBus
from src.runtime.scheduler import TaskScheduler


logger = logging.getLogger(__name__)

class AmadeusRuntime:
    """
    The core runtime daemon for Amadeus AI.
    It encapsulates all state and sub-services and is transport-agnostic.
    """
    def __init__(self, config: Settings):
        self.config = config
        self.event_bus = EventBus()
        self.scheduler = TaskScheduler()

        # Initialize the new Cognitive Core
        self.cognitive_core = CognitiveCore(self.event_bus, persistence_enabled=True)

        self.memory = None
        self.tools = None
        self.llm = None

        self.watchdog = DependencyWatchdog(config)
        self._watchdog_task: asyncio.Task | None = None

        # Phase 2/3 subsystems (wired in start()).
        self.goal_executor: Any | None = None
        self._watchers: list[Any] = []

        # We will lazy-initialize AmadeusService or hold it here
        self.amadeus_service = None

        # Track active tasks for graceful shutdown
        self._active_tasks: set[asyncio.Task] = set()
        self.graceful_shutdown_timeout: int = 30

    async def start(self) -> None:
        logger.info("Starting AmadeusRuntime...")

        # We can wire the container here
        from src.container import get_amadeus_service, get_llm_router
        self.amadeus_service = get_amadeus_service()
        await self.amadeus_service.initialize()  # Initialize semantic router and memory
        self.cognitive_core.configure(self.amadeus_service.handle_command)
        self.llm = get_llm_router()
        self.memory = self.amadeus_service.memory_service
        self.tools = self.amadeus_service.tool_registry

        # Optionally warm up the local LlamaCpp model in the background so the
        # first user message isn't blocked by 3-4s of model loading. This is
        # opt-in (SLM_WARMUP_ON_START, default False) because eager warmup
        # increases startup RAM/CPU on low-end machines; when disabled the
        # first message pays the load cost instead.
        # Fire-and-forget — failure is logged but doesn't block startup.
        if self.llm is not None and self.config.SLM_WARMUP_ON_START:
            logger.info("SLM_WARMUP_ON_START enabled — warming local model in background")
            asyncio.create_task(self.llm.warmup())

        # Start watchdog
        self._watchdog_task = asyncio.create_task(self.watchdog.run())

        # Start the durable scheduler sweeper. The queue is the database, so
        # any tasks scheduled before this point (or before a restart) are
        # picked up here and dispatched back through the agent loop.
        await self.scheduler.start(self._dispatch_scheduled_task)

        # Resume durable long-horizon goals left incomplete by a previous run
        # (Phase 2). The step queue is the database, so this picks up any goal
        # with open steps and continues it from where it stopped.
        try:
            from src.container import get_goal_executor

            self.goal_executor = get_goal_executor()
            resumed = await self.goal_executor.resume_incomplete()  # type: ignore[attr-defined]
            if resumed:
                logger.info("Resumed %d incomplete goal(s) on startup", resumed)
        except Exception:
            logger.exception("Failed to resume incomplete goals on startup")

        # Wire EventBus watchers (Phase 3) — event-driven autonomy. Tier-gated
        # and individually flag-disablable; a no-op when disabled.
        try:
            from src.runtime.watchers import start_watchers

            self._watchers = await start_watchers(
                self.config, self.event_bus, self.amadeus_service
            )
        except Exception:
            logger.exception("Failed to start event watchers")

        await self.event_bus.emit("runtime.started", {"version": self.config.ASSISTANT_VERSION})
        logger.info("AmadeusRuntime started successfully.")

    async def _dispatch_scheduled_task(self, prompt: str, session_id: str) -> None:
        """Execute a due scheduled task through the agent loop (proactive path)."""
        if not self.amadeus_service:
            raise RuntimeError("AmadeusRuntime not started")
        from src.core.domain.context import RequestContext
        from src.core.domain.models import PermissionProfile

        # Least privilege: background/scheduled work runs at STANDARD, not full
        # system access. Tasks needing host/dev tools must be designed explicitly.
        context = RequestContext(
            request_id="scheduled-task",
            session_id=session_id or "background",
            user_id="system",
            permissions=PermissionProfile.STANDARD,
        )
        await self.amadeus_service.handle_background_event(prompt, context=context)

    async def stop(self) -> None:
        logger.info("Stopping AmadeusRuntime...")
        await self.event_bus.emit("runtime.stopping", {})

        # Stop Phase 3 watchers.
        for watcher in self._watchers:
            try:
                await watcher.stop()
            except Exception:
                logger.exception("Error stopping watcher %s", watcher)
        self._watchers = []

        await self.scheduler.stop()

        if self.watchdog:
            self.watchdog.stop()
        if self._watchdog_task:
            await self._watchdog_task

        # Graceful shutdown of active tasks
        if self._active_tasks:
            logger.info("Waiting up to %ds for %d active tasks to finish...", self.graceful_shutdown_timeout, len(self._active_tasks))
            _done, pending = await asyncio.wait(
                self._active_tasks,
                timeout=self.graceful_shutdown_timeout
            )
            if pending:
                logger.warning("Cancelling %d tasks that did not complete within the timeout.", len(pending))
                for t in pending:
                    t.cancel()

        logger.info("AmadeusRuntime stopped.")

    async def process_task(self, context: RequestContext, input_text: str) -> str:
        """
        Main entry point for processing a natural language task.
        Routes through the CognitiveCore lifecycle, which currently wraps the
        proven AmadeusService execution path while adding explicit plans,
        observations, reflections, events, and persistence.
        """
        if not self.amadeus_service:
            raise RuntimeError("AmadeusRuntime not started")

        current_task = asyncio.current_task()
        if current_task:
            self._active_tasks.add(current_task)

        await self.event_bus.emit("task.started", {"request_id": context.request_id, "input": input_text})
        try:
            result = await self.cognitive_core.process(input_text, context)
            await self.event_bus.emit("task.completed", {"request_id": context.request_id, "success": True})
            return result
        except Exception as e:
            await self.event_bus.emit("task.failed", {"request_id": context.request_id, "error": str(e)})
            raise
        finally:
            if current_task is not None and current_task in self._active_tasks:
                self._active_tasks.remove(current_task)

    async def execute_tool(self, context: RequestContext, tool_name: str, args: dict) -> Any:
        """
        Execute a specific tool directly bypassing the LLM.
        """
        if not self.amadeus_service:
            raise RuntimeError("AmadeusRuntime not started")

        await self.event_bus.emit("tool.started", {"request_id": context.request_id, "tool_name": tool_name})
        try:
            dispatcher = self.amadeus_service._tool_dispatcher
            result = await dispatcher.dispatch(tool_name, args, context)
            if result.success:
                await self.event_bus.emit("tool.completed", {"request_id": context.request_id, "tool_name": tool_name})
            else:
                await self.event_bus.emit("tool.failed", {"request_id": context.request_id, "tool_name": tool_name, "error": result.error_message})
            return result
        except Exception as e:
            await self.event_bus.emit("tool.failed", {"request_id": context.request_id, "tool_name": tool_name, "error": str(e)})
            raise
