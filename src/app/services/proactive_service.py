"""
Proactive Checking Service for Amadeus AI.

This service iterates through defined master user channels
and triggers the AmadeusService's background event processor to
proactively check for tasks, reminders, or system alerts and send notifications.
"""

import asyncio
import logging
import uuid
from datetime import datetime

from src.core.config import get_settings
from src.core.domain.models import PermissionProfile


logger = logging.getLogger(__name__)


async def run_proactive_checks() -> None:
    """
    Cron job function that checks active tasks/reminders/system events
    and sends messages to the master user on configured messaging platforms.
    """
    settings = get_settings()

    platforms = []
    telegram_id = getattr(settings, "MASTER_TELEGRAM_CHAT_ID", None)
    if telegram_id:
        platforms.append(("telegram", telegram_id))

    if not platforms:
        logger.info("No MASTER users configured. Skipping proactive checks.")
        return

    from src.container import global_container
    from src.core.domain.context import RequestContext

    current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")

    for platform_name, user_id in platforms:
        logger.info("Running proactive checks for %s / %s", platform_name, user_id)

        try:
            # We use the user_id as the session_id to maintain conversation context for that user
            # just as the webhooks do.
            service = global_container.amadeus_service()

            # Prune stale memories to prevent unbounded Turbovec index growth
            if hasattr(service, "memory_service") and service.memory_service:
                pruned = await service.memory_service.prune_stale_memories(
                    session_id=user_id, older_than_days=90
                )
                if pruned > 0:
                    logger.info("Pruned %d stale memories for %s", pruned, user_id)

            context = RequestContext(
                request_id=str(uuid.uuid4()),
                session_id=user_id,
                user_id=user_id,
                permissions=PermissionProfile.SYSTEM_FULL,
                trace_id=str(uuid.uuid4()),
                cancellation_token=asyncio.Event(),
            )

            # The prompt to trigger analysis and action
            prompt = (
                f"SYSTEM BACKGROUND EVENT: It is currently {current_time}. "
                "Review my pending tasks, recent reminders, and current system resource statuses. "
                "Are there any past due tasks, soon-to-be-due reminders, or critical system alerts? "
                f"If there are, MUST use the send_message tool or send_outbound_message to notify me on {platform_name} at ID {user_id}. "
                "Include a summary of what needs attention. "
                "If everything is fine and nothing needs attention, just finish the task silently without bothering me."
            )

            # Submitting it as a background event processes it via the agent Orchestrator internally
            await service.handle_background_event(prompt, context=context)

        except Exception as e:
            logger.error("Error during proactive check for %s: %s", platform_name, e, exc_info=True)
