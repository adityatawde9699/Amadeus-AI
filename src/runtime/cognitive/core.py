"""Cognitive Core state machine for Amadeus AI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from src.core.domain.context import RequestContext
from src.runtime.cognitive.models import (
    CognitiveContext,
    ExecutionState,
    Observation,
    Plan,
    PlanStatus,
    PlanStep,
    Reflection,
    StepStatus,
)
from src.runtime.events import EventBus


logger = logging.getLogger(__name__)

TaskHandler = Callable[[str, RequestContext], Awaitable[str]]


class CognitiveCore:
    """Central state machine for planning, execution, verification, and memory commit.

    This first production slice intentionally wraps the proven `AmadeusService`
    execution path instead of replacing it with untested autonomous planning.
    The runtime now gets explicit plans, steps, observations, reflections, events,
    and persistence while preserving current behavior.
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
        """Attach runtime dependencies after DI container startup."""
        self._task_handler = task_handler

    async def process(self, task: str, request_context: RequestContext) -> str:
        """Process a task through the explicit cognitive lifecycle."""
        ctx = CognitiveContext(
            request_id=request_context.request_id,
            session_id=request_context.session_id,
            user_id=request_context.user_id,
        )
        await self._emit("task.submitted", ctx, {"input": task})

        while ctx.state not in (ExecutionState.DONE, ExecutionState.BLOCKED):
            logger.debug("CognitiveCore [%s]: state=%s", ctx.request_id, ctx.state)
            await self._transition(ctx, task, request_context)

        if ctx.state == ExecutionState.DONE:
            return ctx.final_output or self._synthesize_final_result(ctx)
        return ctx.final_output or "Task was blocked or failed during execution."

    async def _transition(
        self,
        ctx: CognitiveContext,
        task: str,
        request_context: RequestContext,
    ) -> None:
        """Execute the current state and move to the next state."""
        if ctx.state == ExecutionState.RECEIVED:
            ctx.plan = Plan(
                request_id=ctx.request_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                original_task=task,
            )
            await self._emit("plan.created", ctx, {"plan_id": ctx.plan.id})
            await self._persist_plan(ctx.plan)
            ctx.state = ExecutionState.CONTEXTUALIZING
            return

        if ctx.state == ExecutionState.CONTEXTUALIZING:
            await self._emit("cognitive.contextualizing", ctx, {})
            ctx.state = ExecutionState.PLANNING
            return

        if ctx.state == ExecutionState.PLANNING:
            await self._emit("cognitive.planning", ctx, {})
            if ctx.plan is None:
                ctx.state = ExecutionState.BLOCKED
                ctx.final_output = "No execution plan could be created."
                return

            step = PlanStep(
                name="Handle request through service facade",
                description=task,
                tool="amadeus_service.handle_command",
                risk_level="low",
            )
            ctx.plan.steps.append(step)
            ctx.plan.status = PlanStatus.READY
            await self._persist_step(ctx.plan, step)
            await self._persist_plan_status(ctx.plan, PlanStatus.READY)
            ctx.state = ExecutionState.EXECUTING
            return

        if ctx.state == ExecutionState.EXECUTING:
            if ctx.plan is None:
                ctx.state = ExecutionState.BLOCKED
                ctx.final_output = "No plan is available for execution."
                return

            ready_steps = ctx.plan.get_ready_steps()
            if not ready_steps:
                if all(step.status == StepStatus.COMPLETED for step in ctx.plan.steps):
                    ctx.plan.status = PlanStatus.COMPLETED
                    await self._persist_plan_status(ctx.plan, PlanStatus.COMPLETED)
                    ctx.state = ExecutionState.MEMORY_COMMIT
                else:
                    ctx.plan.status = PlanStatus.BLOCKED
                    ctx.final_output = "Plan has no executable steps."
                    await self._persist_plan_status(
                        ctx.plan,
                        PlanStatus.BLOCKED,
                        error_message=ctx.final_output,
                    )
                    ctx.state = ExecutionState.BLOCKED
                return

            for step in ready_steps:
                await self._execute_step(ctx, step, request_context)
            ctx.state = ExecutionState.VERIFYING
            return

        if ctx.state == ExecutionState.VERIFYING:
            if ctx.plan:
                for step in ctx.plan.steps:
                    if step.status == StepStatus.VERIFYING:
                        step.status = StepStatus.COMPLETED
                        step.completed_at = datetime.now(UTC)
                        step.reflection = Reflection(
                            step_id=step.id,
                            confidence=1.0,
                            analysis="Facade execution completed without raising an exception.",
                            suggested_action="memory_commit",
                        )
                        await self._persist_step(ctx.plan, step)
                        await self._persist_reflection(ctx.plan, step, step.reflection)
            ctx.state = ExecutionState.REFLECTING
            return

        if ctx.state == ExecutionState.REFLECTING:
            if ctx.plan and all(step.status == StepStatus.COMPLETED for step in ctx.plan.steps):
                ctx.plan.status = PlanStatus.COMPLETED
                await self._persist_plan_status(
                    ctx.plan,
                    PlanStatus.COMPLETED,
                    final_output=ctx.final_output,
                )
                ctx.state = ExecutionState.MEMORY_COMMIT
            else:
                ctx.state = ExecutionState.BLOCKED
                ctx.final_output = ctx.final_output or "Plan verification did not complete."
            return

        if ctx.state == ExecutionState.MEMORY_COMMIT:
            await self._emit(
                "memory.committed",
                ctx,
                {"plan_id": ctx.plan.id if ctx.plan else None},
            )
            ctx.state = ExecutionState.DONE

    async def _execute_step(
        self,
        ctx: CognitiveContext,
        step: PlanStep,
        request_context: RequestContext,
    ) -> None:
        if ctx.plan is None:
            return

        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(UTC)
        await self._persist_step(ctx.plan, step)
        await self._emit(
            "plan.step.started",
            ctx,
            {"plan_id": ctx.plan.id, "step_id": step.id, "tool": step.tool},
        )

        try:
            if self._task_handler is None:
                raise RuntimeError("CognitiveCore has no task handler configured")

            result = await self._task_handler(ctx.plan.original_task, request_context)
            ctx.final_output = result
            observation = Observation(
                source=step.tool or "cognitive_core",
                content=result,
                success=True,
                metadata={"facade": True},
            )
            step.observations.append(observation)
            step.status = StepStatus.VERIFYING
            await self._persist_observation(ctx.plan, step, observation)
            await self._emit(
                "plan.step.completed",
                ctx,
                {"plan_id": ctx.plan.id, "step_id": step.id, "success": True},
            )
        except Exception as exc:
            message = str(exc)
            ctx.final_output = f"Task failed during execution: {message}"
            observation = Observation(
                source=step.tool or "cognitive_core",
                content=message,
                success=False,
                metadata={"error_type": type(exc).__name__},
            )
            step.observations.append(observation)
            step.status = StepStatus.FAILED
            step.completed_at = datetime.now(UTC)
            ctx.plan.status = PlanStatus.FAILED
            await self._persist_observation(ctx.plan, step, observation)
            await self._persist_step(ctx.plan, step)
            await self._persist_plan_status(
                ctx.plan,
                PlanStatus.FAILED,
                error_message=message,
            )
            await self._emit(
                "plan.step.failed",
                ctx,
                {"plan_id": ctx.plan.id, "step_id": step.id, "error": message},
            )
            ctx.state = ExecutionState.BLOCKED

    def _synthesize_final_result(self, ctx: CognitiveContext) -> str:
        """Compile observations into a final answer."""
        if not ctx.plan:
            return "No plan executed."

        outputs = [
            observation.content
            for step in ctx.plan.steps
            for observation in step.observations
            if observation.success
        ]
        if outputs:
            return "\n".join(outputs)
        return "Task completed with no output."

    async def _emit(self, event: str, ctx: CognitiveContext, payload: dict) -> None:
        full_payload = {
            "request_id": ctx.request_id,
            "session_id": ctx.session_id,
            "user_id": ctx.user_id,
            **payload,
        }
        await self.event_bus.emit(event, full_payload)

    async def _with_repo(self, method_name: str, *args: object, **kwargs: object) -> None:
        if not self.persistence_enabled:
            return
        try:
            from src.infra.persistence.database import get_session
            from src.infra.persistence.repositories.cognitive_repository import (
                SQLAlchemyCognitiveRepository,
            )

            async with get_session() as session:
                repo = SQLAlchemyCognitiveRepository(session)
                await asyncio.wait_for(
                    getattr(repo, method_name)(*args, **kwargs),
                    timeout=self.persistence_timeout_seconds,
                )
        except TimeoutError:
            logger.debug("Cognitive persistence timed out for %s", method_name)
        except Exception as exc:
            logger.debug("Cognitive persistence skipped for %s: %s", method_name, exc)

    async def _persist_plan(self, plan: Plan) -> None:
        await self._with_repo("create_plan", plan)

    async def _persist_plan_status(
        self,
        plan: Plan,
        status: PlanStatus,
        final_output: str | None = None,
        error_message: str | None = None,
    ) -> None:
        plan.status = status
        plan.updated_at = datetime.now(UTC)
        await self._with_repo("update_plan_status", plan.id, status, final_output, error_message)

    async def _persist_step(self, plan: Plan, step: PlanStep) -> None:
        await self._with_repo("update_step", plan.id, step)

    async def _persist_observation(
        self,
        plan: Plan,
        step: PlanStep,
        observation: Observation,
    ) -> None:
        await self._with_repo("add_observation", plan.id, step.id, observation)

    async def _persist_reflection(
        self,
        plan: Plan,
        step: PlanStep,
        reflection: Reflection,
    ) -> None:
        await self._with_repo("add_reflection", plan.id, step.id, reflection)
