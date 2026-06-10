import asyncio
import logging
from typing import Any

from src.core.config import Settings
from src.core.domain.context import RequestContext
from src.runtime.events import EventBus
from src.runtime.scheduler import TaskScheduler
from src.infra.resilience.watchdog import DependencyWatchdog
from src.runtime.cognitive.core import CognitiveCore

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

        # Eagerly warm up the local LlamaCpp model in the background so the
        # first user message isn't blocked by 3-4s of model loading.
        # We fire-and-forget — failure is logged but doesn't block startup.
        if self.llm is not None:
            asyncio.create_task(self.llm.warmup())

        # Start watchdog
        self._watchdog_task = asyncio.create_task(self.watchdog.run())
        
        # Wire EventBus
        # TODO: Wire watchdog, tool dispatcher, llm router to event_bus
        
        await self.event_bus.emit("runtime.started", {"version": self.config.ASSISTANT_VERSION})
        logger.info("AmadeusRuntime started successfully.")

    async def stop(self) -> None:
        logger.info("Stopping AmadeusRuntime...")
        await self.event_bus.emit("runtime.stopping", {})
        
        if self.watchdog:
            self.watchdog.stop()
        if self._watchdog_task:
            await self._watchdog_task
            
        # Graceful shutdown of active tasks
        if self._active_tasks:
            logger.info("Waiting up to %ds for %d active tasks to finish...", self.graceful_shutdown_timeout, len(self._active_tasks))
            done, pending = await asyncio.wait(
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
