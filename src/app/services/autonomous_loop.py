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

    async def start(self) -> None:
        """Start the background observation loop."""
        self._running = True
        logger.info(f"Starting Autonomous Observation Loop (interval: {self.interval_minutes}m)")
        asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Stop the background observation loop."""
        logger.info("Stopping Autonomous Observation Loop.")
        self._running = False

    async def _loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                # Wait for the interval
                await asyncio.sleep(self.interval_minutes * 60)

                # During the cycle, we trigger a background thought for each active session.
                # In a real app we'd load active user session IDs from the database.
                for s_id in self.session_ids:
                    await self._trigger_observation(s_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in autonomous loop: {e}", exc_info=True)
                await asyncio.sleep(60)  # Backoff on error

    async def _trigger_observation(self, session_id: str) -> None:
        """Trigger the agent to observe its state."""
        logger.info(f"Triggering autonomous observation for session {session_id}")
        try:
            from src.app.services.amadeus_service import AmadeusService

            svc = AmadeusService(session_id=session_id)
            await svc.initialize()

            prompt = (
                f"SYSTEM BACKGROUND EVENT: It is currently {datetime.now().strftime('%H:%M')}. "
                "Review recent messages or your long-term memory. If there is something "
                "important to notify the user about proactively, use tools to send an outbound message (like send_email or platform integrations). "
                "If not, finish the task silently without bothering the user."
            )
            # Submit to service as a background event
            await svc.handle_background_event(prompt)
        except Exception as e:
            logger.exception(f"Failed to run observation for session {session_id}: {e}")
