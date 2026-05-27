import time
import logging
import asyncio
from enum import Enum
from collections.abc import Callable, Awaitable
from typing import Any, TypeVar

from src.runtime.events import EventBus

logger = logging.getLogger(__name__)

T = TypeVar('T')

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenException(Exception):
    pass

class CircuitBreaker:
    """
    Prevents cascading failures by stopping execution if an external dependency 
    is repeatedly failing.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        event_bus: EventBus | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.event_bus = event_bus
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute func through the circuit breaker."""
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("CircuitBreaker '%s' moving to HALF_OPEN state.", self.name)
                else:
                    raise CircuitBreakerOpenException(f"Circuit '{self.name}' is OPEN.")

        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            await self._record_failure()
            raise e

        # Success - reset
        if self.state != CircuitState.CLOSED:
            async with self._lock:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info("CircuitBreaker '%s' CLOSED. Recovered.", self.name)
                if self.event_bus:
                    await self.event_bus.emit("circuit.closed", {"circuit": self.name})

        return result

    async def _record_failure(self) -> None:
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    self.state = CircuitState.OPEN
                    logger.warning("CircuitBreaker '%s' OPENED after %d failures.", self.name, self.failure_count)
                    if self.event_bus:
                        await self.event_bus.emit("circuit.opened", {"circuit": self.name})
