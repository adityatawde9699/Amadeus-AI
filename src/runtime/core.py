import asyncio
import logging
from typing import Any

from src.core.config import Settings
from src.core.domain.context import RequestContext
from src.runtime.events import EventBus
from src.runtime.scheduler import TaskScheduler
from src.infra.resilience.watchdog import DependencyWatchdog

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
        
        self.memory = None
        self.tools = None
        self.llm = None
        
        self.watchdog = DependencyWatchdog(config)
        self._watchdog_task: asyncio.Task | None = None
        
        # We will lazy-initialize AmadeusService or hold it here
        self.amadeus_service = None

    async def start(self) -> None:
        logger.info("Starting AmadeusRuntime...")
        
        # We can wire the container here
        from src.container import get_amadeus_service, get_llm_router
        self.amadeus_service = get_amadeus_service()
        await self.amadeus_service.initialize()  # Initialize semantic router and memory
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
            
        logger.info("AmadeusRuntime stopped.")

    async def process_task(self, context: RequestContext, input_text: str) -> str:
        """
        Main entry point for processing a natural language task.
        Delegates to the internal AmadeusService.
        """
        if not self.amadeus_service:
            raise RuntimeError("AmadeusRuntime not started")
            
        await self.event_bus.emit("task.started", {"request_id": context.request_id, "input": input_text})
        try:
            # We assume handle_command is the main entry point
            result = await self.amadeus_service.handle_command(user_input=input_text, context=context)
            await self.event_bus.emit("task.completed", {"request_id": context.request_id, "success": True})
            return result
        except Exception as e:
            await self.event_bus.emit("task.failed", {"request_id": context.request_id, "error": str(e)})
            raise

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
