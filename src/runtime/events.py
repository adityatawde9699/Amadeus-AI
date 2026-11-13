import asyncio
import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)


class EventBus:
    """
    Asynchronous pub-sub EventBus for internal system events.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}

    def on(
        self,
        event: str,
        handler: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """Register a handler for a specific event type.

        Can be called directly or used as a decorator::

            bus.on("event", my_handler)

            @bus.on("event")
            async def my_handler(payload): ...
        """

        def _register(fn: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
            if event not in self._subscribers:
                self._subscribers[event] = []
            self._subscribers[event].append(fn)
            logger.debug("Registered handler for event: %s", event)
            return fn

        if handler is not None:
            return _register(handler)
        return _register

    def off(self, event: str, handler: Callable[[dict[str, Any]], Any]) -> bool:
        """Unregister a handler from a specific event. Returns True if removed."""
        handlers = self._subscribers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("Unregistered handler for event: %s", event)
            return True
        return False

    def clear(self) -> None:
        """Clear all registered event handlers."""
        self._subscribers.clear()

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        """
        Emit an event to all registered handlers asynchronously.
        Handlers can be coroutines or regular functions.
        """
        handlers = self._subscribers.get(event, [])
        if not handlers:
            return

        async def _run_handler(h: Callable[..., Any], p: dict[str, Any]) -> None:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h(p)
                else:
                    h(p)
            except Exception as e:
                logger.exception(f"Error in event handler for {event}: {e}")

        # Fire and forget all handlers concurrently
        tasks = [_run_handler(h, payload) for h in handlers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
