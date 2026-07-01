import asyncio
import logging

from src.core.config import Settings
from src.runtime.events import EventBus


logger = logging.getLogger(__name__)

class DependencyWatchdog:
    def __init__(self, settings: Settings, event_bus: EventBus | None = None):
        self.settings = settings
        self.event_bus = event_bus
        self.dependencies = {
            "redis": False,
            "qdrant": False,
            "llm_providers": {}
        }
        self._running = False

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
            logger.debug("Watchdog: Redis check failed - %s", e)
            return False

    async def check_qdrant(self) -> bool:
        # Qdrant client check (simplified HTTP check if possible or just use client)
        # Since we use local path in some cases, if it's local it's always "up", but for a network Qdrant, we'd ping.
        # Assuming local path based on persistence for now.
        return self.settings.MEMORY_ENABLED

    async def check_llm_providers(self) -> dict[str, bool]:
        # Quick health checks for LLMs.
        # For simplicity, we just mark them as true unless circuit breaker is open.
        # This will be integrated tighter with LLMRouter's circuit breakers in the future.
        return {
            "llama_cpp": True,
            "groq": True,
            "gemini": True,
        }

    async def run(self, interval_seconds: int = 30):
        self._running = True
        logger.info("DependencyWatchdog started")
        while self._running:
            try:
                prev_redis = self.dependencies.get("redis")
                curr_redis = await self.check_redis()
                self.dependencies["redis"] = curr_redis
                if self.event_bus and prev_redis != curr_redis:
                    await self.event_bus.emit(
                        "provider.recovered" if curr_redis else "provider.disabled",
                        {"provider": "redis"}
                    )

                self.dependencies["qdrant"] = await self.check_qdrant()
                self.dependencies["llm_providers"] = await self.check_llm_providers()

                # Graceful degradation logic
                # If all cloud providers are down, we could dynamically set LOCAL_ONLY_MODE = True

            except asyncio.CancelledError:
                self._running = False
                break
            except Exception as e:
                logger.exception("Watchdog error: %s", e)

            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False
