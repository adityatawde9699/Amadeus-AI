"""
GoalExecutor — durable, restart-safe execution of long-horizon goals (Phase 2).

A goal is decomposed once into an ordered list of expert subtasks persisted as
``goal_steps`` rows (see :class:`GoalStepORM`). The executor then drives the
goal: it claims the next PENDING step, runs the subtask through the agent loop,
records the result, and advances. When every step is DONE the parent goal is
marked complete.

Because the step queue lives in the database, a daemon restart loses nothing:
:meth:`resume_incomplete` scans for goals that still have open steps and
continues them. Each step runs on its own LangGraph ``thread_id``
(``goal-<id>-step-<seq>``) so the checkpointer can resume an interrupted step.

Wiring:
  * ``execute_goal`` tool → :meth:`start_goal`
  * :class:`AmadeusRuntime` startup → :meth:`resume_incomplete`
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from src.infra.persistence.database import get_session
from src.infra.persistence.repositories.goal_step_repository import (
    GoalStep,
    GoalStepRepository,
)


if TYPE_CHECKING:
    from src.core.interfaces.repositories import IGoalRepository


logger = logging.getLogger(__name__)

# run_subtask(subtask, thread_id, expert) -> result text
RunSubtaskFn = Callable[[str, str, str | None], Awaitable[str]]
# decompose(goal_text, max_steps) -> [{"expert": str, "subtask": str}, ...]
DecomposeFn = Callable[[str, int], Awaitable[list[dict]]]


class GoalExecutor:
    """Drives persisted multi-step goals to completion, resumably."""

    def __init__(
        self,
        goal_repository: IGoalRepository,
        run_subtask: RunSubtaskFn,
        decompose: DecomposeFn | None = None,
        *,
        max_steps: int = 8,
    ) -> None:
        self._goals = goal_repository
        self._run_subtask = run_subtask
        self._decompose = decompose
        self._max_steps = max_steps
        # One lock per goal so a resume and a fresh start can't double-drive it.
        self._locks: dict[int, asyncio.Lock] = {}
        self._driving: set[asyncio.Task] = set()

    def _lock_for(self, goal_id: int) -> asyncio.Lock:
        lock = self._locks.get(goal_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[goal_id] = lock
        return lock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_goal(self, goal_id: int, *, background: bool = True) -> str:
        """Decompose (if needed) and begin executing a goal.

        When ``background`` is True the drive runs as a fire-and-forget task and
        this returns immediately with an acknowledgement (the caller is usually
        a tool whose result is a short status line); otherwise it blocks until
        the goal finishes (used by tests).
        """
        goal = await self._goals.get_by_id(goal_id)
        if goal is None:
            return f"Goal #{goal_id} not found."

        async with get_session() as session:
            repo = GoalStepRepository(session)
            if not await repo.has_steps(goal_id):
                steps = await self._plan_steps(goal.title, goal.description)
                if not steps:
                    return f"Could not decompose goal #{goal_id} into steps."
                await repo.create_steps(goal_id, steps)
                logger.info(
                    "Goal #%d decomposed into %d step(s)", goal_id, len(steps)
                )

        if background:
            task = asyncio.create_task(self._drive(goal_id))
            self._driving.add(task)
            task.add_done_callback(self._driving.discard)
            return (
                f"Goal #{goal_id} ('{goal.title}') started — executing its steps "
                f"in the background (persisted; survives restarts)."
            )
        return await self._drive(goal_id)

    async def resume_incomplete(self) -> int:
        """Resume every goal that still has open steps. Returns the count."""
        try:
            async with get_session() as session:
                repo = GoalStepRepository(session)
                # Recover steps left RUNNING by a crash mid-step.
                requeued = await repo.requeue_stuck_running()
                goal_ids = await repo.goal_ids_with_open_steps()
            if requeued:
                logger.info("Requeued %d goal step(s) stuck in RUNNING", requeued)
        except Exception:
            logger.exception("GoalExecutor.resume_incomplete scan failed")
            return 0

        for goal_id in goal_ids:
            task = asyncio.create_task(self._drive(goal_id))
            self._driving.add(task)
            task.add_done_callback(self._driving.discard)
        if goal_ids:
            logger.info("Resuming %d incomplete goal(s): %s", len(goal_ids), goal_ids)
        return len(goal_ids)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _plan_steps(self, title: str, description: str) -> list[dict]:
        goal_text = f"{title}. {description}".strip()
        if self._decompose is not None:
            try:
                steps = await self._decompose(goal_text, self._max_steps)
                if steps:
                    return steps[: self._max_steps]
            except Exception:
                logger.exception("Goal decomposition failed — using single step")
        # Fallback: treat the whole goal as a single generalist step.
        return [{"expert": "generalist", "subtask": goal_text}]

    async def _drive(self, goal_id: int) -> str:
        """Run the goal's steps in order until none remain or one fails."""
        async with self._lock_for(goal_id):
            completed: list[str] = []
            while True:
                async with get_session() as session:
                    step = await GoalStepRepository(session).claim_next_step(goal_id)
                if step is None:
                    break  # no more PENDING steps

                ok, result = await self._run_step(goal_id, step)
                async with get_session() as session:
                    repo = GoalStepRepository(session)
                    if ok:
                        await repo.mark_done(step.id, result)
                        completed.append(result)
                    else:
                        await repo.mark_failed(step.id, result)

                if not ok:
                    logger.warning(
                        "Goal #%d halted at step %d: %s", goal_id, step.seq, result
                    )
                    return f"Goal #{goal_id} halted at step {step.seq + 1}: {result}"

            # All steps consumed — complete the goal if nothing is left open.
            async with get_session() as session:
                open_count = await GoalStepRepository(session).open_step_count(goal_id)
            if open_count == 0:
                try:
                    await self._goals.mark_complete(goal_id)
                except Exception:
                    logger.exception("Failed to mark goal #%d complete", goal_id)
                logger.info("Goal #%d completed (%d steps)", goal_id, len(completed))
                return f"Goal #{goal_id} completed."
            return f"Goal #{goal_id} paused with {open_count} step(s) still open."

    async def _run_step(self, goal_id: int, step: GoalStep) -> tuple[bool, str]:
        thread_id = f"goal-{goal_id}-step-{step.seq}"
        try:
            result = await self._run_subtask(step.subtask, thread_id, step.expert)
            return True, (result or "(no output)")
        except Exception as exc:
            logger.exception("Goal #%d step %d dispatch failed", goal_id, step.seq)
            return False, str(exc)
