import asyncio
import contextlib
import logging

from src.core.config import Settings
from src.runtime.events import EventBus


logger = logging.getLogger(__name__)


class DependencyWatchdog:
    """Periodically checks whether optional infrastructure dependencies
    (Redis, Qdrant, LLM providers) are reachable and emits events on
    state transitions so the rest of the runtime can degrade gracefully.

    Usage::

        watchdog = DependencyWatchdog(settings, event_bus)
        task = asyncio.create_task(watchdog.run())
        # ... later ...
        watchdog.stop()
        await task
    """

    def __init__(self, settings: Settings, event_bus: EventBus | None = None):
        self.settings = settings
        self.event_bus = event_bus
        self.dependencies: dict = {
            "redis": False,
            "qdrant": False,
            "llm_providers": {},
        }
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Individual health checks
    # ------------------------------------------------------------------

    async def check_redis(self) -> bool:
        if not self.settings.REDIS_URL:
            return False
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)
            await client.ping()
            await client.aclose()
            return True
        except Exception as e:
            logger.debug("Watchdog: Redis check failed — %s", e)
            return False

    async def check_qdrant(self) -> bool:
        # Local-path Qdrant is always "up"; a network Qdrant would need a ping.
        return self.settings.MEMORY_ENABLED

    async def check_llm_providers(self) -> dict[str, bool]:
        # Placeholder — integrated tightly with LLMRouter circuit breakers later.
        return {
            "llama_cpp": True,
            "groq": True,
            "gemini": True,
        }

    # ------------------------------------------------------------------
    # Run / stop
    # ------------------------------------------------------------------

    async def run(self, interval_seconds: int = 30) -> None:
        """Main watchdog loop — runs until ``stop()`` is called."""
        self._stop_event.clear()
        logger.info("DependencyWatchdog started (interval=%ds)", interval_seconds)
        while not self._stop_event.is_set():
            try:
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Watchdog sweep error")

            # Sleep for *interval_seconds*, but wake immediately on stop().
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)

        logger.info("DependencyWatchdog stopped.")

    async def _check_all(self) -> None:
        """Run all checks and emit events on state changes."""
        prev_redis = self.dependencies.get("redis")
        curr_redis = await self.check_redis()
        self.dependencies["redis"] = curr_redis
        if self.event_bus and prev_redis != curr_redis:
            await self.event_bus.emit(
                "provider.recovered" if curr_redis else "provider.disabled",
                {"provider": "redis"},
            )

        self.dependencies["qdrant"] = await self.check_qdrant()
        self.dependencies["llm_providers"] = await self.check_llm_providers()

    def stop(self) -> None:
        """Signal the watchdog loop to exit cleanly."""
        self._stop_event.set()
