import asyncio
import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)

class EventBus:
    """
    Asynchronous pub-sub EventBus for internal system events.
    """
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}

    def on(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a handler for a specific event type."""
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(handler)
        logger.debug(f"Registered handler for event: {event}")

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        """
        Emit an event to all registered handlers asynchronously.
        Handlers can be coroutines or regular functions.
        """
        handlers = self._subscribers.get(event, [])
        if not handlers:
            return

        async def _run_handler(h: Callable, p: dict):
            try:
                if asyncio.iscoroutinefunction(h):
                    await h(p)
                else:
                    h(p)
            except Exception as e:
                logger.error(f"Error in event handler for {event}: {e}")

        # Fire and forget all handlers concurrently
        tasks = [_run_handler(h, payload) for h in handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
