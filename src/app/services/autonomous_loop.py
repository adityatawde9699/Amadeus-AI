"""
Autonomous Observation Loop.

This allows the agent to iteratively 'wake up' and check its environment
(time, memory context, or external triggers) without direct user prompting.
Inspired by OpenClaw's background routines.
"""

import asyncio
import logging
from datetime import datetime


logger = logging.getLogger(__name__)


class AutonomousObservationLoop:
    def __init__(self, interval_minutes: int = 60, session_ids: list[str] | None = None) -> None:
        self.interval_minutes = interval_minutes
        self.session_ids = session_ids or []  # List of active session IDs to monitor
        self._running = False
        self._recent_observations: dict[str, list[datetime]] = {}

    async def start(self) -> None:
        """Start the background observation loop."""
        self._running = True
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        logger.info(
            "Starting Autonomous Observation Loop (interval: %sm)", self.interval_minutes
        )
        # DR-01: Store task reference so exceptions are never silently swallowed.
        self._task = asyncio.create_task(self._loop())
        self._task.add_done_callback(self._on_task_done)

    def stop(self) -> None:
        """Stop the background observation loop."""
        logger.info("Stopping Autonomous Observation Loop.")
        self._running = False
        if hasattr(self, "_task") and self._task and not self._task.done():
            self._task.cancel()

    def _on_task_done(self, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        """DR-01: Log any unhandled exception from the background loop task."""
        try:
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "AutonomousObservationLoop task raised an unhandled exception: %s",
                    exc, exc_info=exc,
                )
        except asyncio.CancelledError:
            logger.info("AutonomousObservationLoop task was cancelled cleanly.")

    async def _loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                # 1. Check System Health
                await self._check_system_health()

                # 2. Trigger Observations for sessions
                for s_id in self.session_ids:
                    await self._trigger_observation(s_id)
                
                # Wait for the interval
                await asyncio.sleep(self.interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in autonomous loop: %s", e, exc_info=True)
                await asyncio.sleep(60)  # Backoff on error

    async def _check_system_health(self) -> None:
        """Monitor system resources and alert if critical."""
        try:
            from src.infra.tools.monitor_tools import get_system_status
            status = get_system_status()
            
            alerts = []
            if status.cpu_usage > 90:
                alerts.append(f"CRITICAL: CPU usage is at {status.cpu_usage}%!")
            if status.memory_usage > 90:
                alerts.append(f"CRITICAL: Memory usage is at {status.memory_usage}%!")
            if status.disk_usage > 95:
                alerts.append(f"CRITICAL: Disk space is almost full ({status.disk_usage}% used)!")
            if status.battery_percent is not None and status.battery_percent < 10 and not status.is_charging:
                alerts.append(f"CRITICAL: Battery is extremely low ({status.battery_percent}%)!")
                
            if alerts and self.session_ids:
                logger.warning("System health alerts detected: %s", alerts)
                from src.container import global_container
                svc = global_container.amadeus_service()
                
                alert_msg = "⚠️ **System Health Alert**\n\n" + "\n".join(alerts)
                # Notify the first session (typically the master user)
                await svc.send_outbound_message(self.session_ids[0], "telegram", alert_msg)
        except Exception as e:
            logger.error("Failed to check system health: %s", e)

    async def _trigger_observation(self, session_id: str) -> None:
        """Trigger the agent to observe its state."""
        try:
            from src.core.config import get_settings
            settings = get_settings()

            # Enforce Rate Limiting
            now = datetime.now()
            history = self._recent_observations.get(session_id, [])
            # Prune history older than 1 hour
            history = [t for t in history if (now - t).total_seconds() < 3600]
            self._recent_observations[session_id] = history

            if len(history) >= settings.PROACTIVE_MESSAGE_LIMIT_PER_HOUR:
                logger.info(
                    "Skipping proactive observation for session %s (Rate limit reached: %d/hr)",
                    session_id, len(history)
                )
                return

            # Record this attempt
            self._recent_observations[session_id].append(now)

            if settings.PROACTIVE_DRY_RUN:
                logger.info("[DRY RUN] Would trigger proactive observation for session %s", session_id)
                return

            logger.info("Triggering autonomous observation for session %s", session_id)
            # ARCH-02: Use the DI container singleton so the observation loop gets the
            # full tool registry, LLM router, and cache — not a lobotomised bare instance.
            from src.container import global_container

            svc = global_container.amadeus_service()

            prompt = (
                f"SYSTEM BACKGROUND EVENT: It is currently {now.strftime('%H:%M')}. "
                "Review recent messages or your long-term memory. If there is something "
                "important to notify the user about proactively, use tools to send an outbound message (like send_email or platform integrations). "
                "If not, finish the task silently without bothering the user."
            )
            # Submit to service as a background event
            await svc.handle_background_event(prompt)
        except Exception as e:
            logger.exception("Failed to run observation for session %s: %s", session_id, e)
