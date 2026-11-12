"""Execution journal for Amadeus AI requests.

Planning, tool use, reflection and human-in-the-loop all happen in the
LangGraph agent graph (``src/app/services/agent_loop.py``), reached through
``AmadeusService.handle_command``. This module previously wrapped that call in
a RECEIVED → CONTEXTUALIZING → PLANNING → EXECUTING → VERIFYING → REFLECTING →
MEMORY_COMMIT state machine whose plan was always one hard-coded step and whose
"verification" was "no exception was raised" (audit finding: cosmetic layer).

It is now what it actually is: a journal. Each request is recorded as one run
(a ``Plan`` with a single step and one observation) in the ``cognitive_*``
tables, and lifecycle events are emitted on the runtime event bus. The class
name and persistence schema are kept for compatibility.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.runtime.cognitive.models import (
    Observation,
    Plan,
    PlanStatus,
    PlanStep,
    StepStatus,
)


if TYPE_CHECKING:
    from src.core.domain.context import RequestContext
    from src.runtime.events import EventBus


logger = logging.getLogger(__name__)

TaskHandler = Callable[[str, "RequestContext"], Awaitable[str]]

# Persisted as the step's tool so stored runs say where the work happened.
AGENT_ENTRYPOINT = "amadeus_service.handle_command"


class CognitiveCore:
    """Record each request as a single journaled run around the agent graph.

    Events (payloads carry ``request_id``, ``session_id``, ``user_id``):
    ``plan.created`` → ``plan.step.started`` →
    ``plan.step.completed`` | ``plan.step.failed`` → ``plan.completed`` | ``plan.failed``.
    """

    def __init__(
        self,
        event_bus: EventBus,
        task_handler: TaskHandler | None = None,
        persistence_enabled: bool = False,
        persistence_timeout_seconds: float = 2.0,
    ) -> None:
        self.event_bus = event_bus
        self._task_handler = task_handler
        self.persistence_enabled = persistence_enabled
        self.persistence_timeout_seconds = persistence_timeout_seconds

    def configure(self, task_handler: TaskHandler) -> None:
        """Attach the agent entry point after DI container startup."""
        self._task_handler = task_handler

    async def process(self, task: str, request_context: RequestContext) -> str:
        """Run ``task`` through the agent and journal the outcome."""
        plan = Plan(
            request_id=request_context.request_id,
            session_id=request_context.session_id,
            user_id=request_context.user_id,
            original_task=task,
            status=PlanStatus.RUNNING,
        )
        step = PlanStep(
            name="Run agent graph",
            description=task,
            tool=AGENT_ENTRYPOINT,
            status=StepStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        plan.steps.append(step)
        await self._persist(("create_plan", (plan,)))
        await self._emit("plan.created", request_context, {"plan_id": plan.id})
        await self._emit(
            "plan.step.started",
            request_context,
            {"plan_id": plan.id, "step_id": step.id, "tool": step.tool},
        )

        try:
            if self._task_handler is None:
                raise RuntimeError("CognitiveCore has no task handler configured")
            result = await self._task_handler(task, request_context)
        except Exception as exc:
            message = str(exc)
            output = f"Task failed during execution: {message}"
            await self._finish(
                plan,
                step,
                request_context,
                Observation(
                    source=AGENT_ENTRYPOINT,
                    content=message,
                    success=False,
                    metadata={"error_type": type(exc).__name__},
                ),
                final_output=None,
                error_message=message,
            )
            return output

        output = result or "Task completed with no output."
        await self._finish(
            plan,
            step,
            request_context,
            Observation(source=AGENT_ENTRYPOINT, content=output, success=True),
            final_output=output,
            error_message=None,
        )
        return output

    async def _finish(
        self,
        plan: Plan,
        step: PlanStep,
        request_context: RequestContext,
        observation: Observation,
        final_output: str | None,
        error_message: str | None,
    ) -> None:
        ok = observation.success
        now = datetime.now(UTC)
        step.observations.append(observation)
        step.status = StepStatus.COMPLETED if ok else StepStatus.FAILED
        step.completed_at = now
        plan.status = PlanStatus.COMPLETED if ok else PlanStatus.FAILED
        plan.updated_at = now

        # One session for all three writes (was ~8 round trips per request).
        await self._persist(
            ("add_observation", (plan.id, step.id, observation)),
            ("update_step", (plan.id, step)),
            ("update_plan_status", (plan.id, plan.status, final_output, error_message)),
        )
        if ok:
            await self._emit(
                "plan.step.completed",
                request_context,
                {"plan_id": plan.id, "step_id": step.id, "success": True},
            )
            await self._emit("plan.completed", request_context, {"plan_id": plan.id})
        else:
            await self._emit(
                "plan.step.failed",
                request_context,
                {"plan_id": plan.id, "step_id": step.id, "error": error_message},
            )
            await self._emit(
                "plan.failed", request_context, {"plan_id": plan.id, "error": error_message}
            )

    async def _emit(self, event: str, ctx: RequestContext, payload: dict) -> None:
        await self.event_bus.emit(
            event,
            {
                "request_id": ctx.request_id,
                "session_id": ctx.session_id,
                "user_id": ctx.user_id,
                **payload,
            },
        )

    async def _persist(self, *ops: tuple[str, tuple[object, ...]]) -> None:
        """Best-effort journal writes; never fail or noticeably delay the request."""
        if not self.persistence_enabled:
            return
        try:
            from src.infra.persistence.database import get_session
            from src.infra.persistence.repositories.cognitive_repository import (
                SQLAlchemyCognitiveRepository,
            )

            async with get_session() as session:
                repo = SQLAlchemyCognitiveRepository(session)
                for method_name, args in ops:
                    await asyncio.wait_for(
                        getattr(repo, method_name)(*args),
                        timeout=self.persistence_timeout_seconds,
                    )
        except TimeoutError:
            logger.debug("Execution journal write timed out (%s)", [op[0] for op in ops])
        except Exception as exc:
            logger.debug("Execution journal write skipped (%s): %s", [op[0] for op in ops], exc)
