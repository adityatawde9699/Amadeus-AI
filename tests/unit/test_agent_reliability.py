"""
Phase 11 — Agent Reliability Unit Tests.

Tests every agent-loop and reliability fix from the audit:
  - AG-01: Cycle detection (semantic + frequency bypass)
  - AG-02: SYNTHESIZE reports success=False when all observations are errors
  - DR-01: AutonomousObservationLoop stores task reference + done-callback
  - DR-02: AgentOrchestrator.shutdown() cancels worker task
  - DR-03: APScheduler shutdown(wait=True) is set
  - HITL deny-by-default when no confirmation_callback
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# AG-01 — Cycle detection
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# DR-01 — AutonomousObservationLoop task tracking
# ---------------------------------------------------------------------------


class TestAutonomousLoopTaskTracking:
    """AutonomousObservationLoop must store task reference and register done-callback."""

    @pytest.mark.asyncio
    async def test_task_stored_after_start(self):
        """self._task must be set after start()."""
        from src.app.services.autonomous_loop import AutonomousObservationLoop

        loop = AutonomousObservationLoop(interval_minutes=999, session_ids=["s1"])

        async def fake_loop(self_inner):
            await asyncio.sleep(999)

        with patch.object(
            AutonomousObservationLoop, "_loop", fake_loop
        ):
            await loop.start()

        assert hasattr(loop, "_task"), "_task attribute must exist after start()"
        assert loop._task is not None, "_task must not be None"
        loop._task.cancel()
        try:
            await loop._task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_done_callback_registered(self):
        """_on_task_done must be registered as a done-callback on the task."""
        from src.app.services.autonomous_loop import AutonomousObservationLoop

        loop = AutonomousObservationLoop(interval_minutes=999, session_ids=["s1"])
        callbacks_registered: list = []
        original_add_done_callback = asyncio.Task.add_done_callback

        with patch("asyncio.create_task") as mock_create_task:
            mock_task = MagicMock(spec=asyncio.Task)
            mock_create_task.return_value = mock_task
            mock_task.add_done_callback.side_effect = lambda cb: callbacks_registered.append(cb)
            await loop.start()

        assert any(
            getattr(cb, "__name__", "") == "_on_task_done"
            or cb == loop._on_task_done
            for cb in callbacks_registered
        ), "_on_task_done must be registered as a done-callback"

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() must cancel the stored asyncio task."""
        from src.app.services.autonomous_loop import AutonomousObservationLoop

        loop = AutonomousObservationLoop(interval_minutes=999, session_ids=["s1"])
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        loop._task = mock_task

        loop.stop()

        mock_task.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# DR-02 — AgentOrchestrator.shutdown()
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# HITL — Deny by default when no callback set
# ---------------------------------------------------------------------------


class TestHITLDenyByDefault:
    """Destructive tools must be denied when no confirmation_callback is set."""

    @pytest.mark.asyncio
    async def test_destructive_tool_denied_without_callback(self):
        """execute() must return success=False for requires_confirmation tools when callback=None."""
        from src.infra.tools.base import Tool, ToolCategory, ToolExecutor

        def delete_file(file_path: str) -> str:
            return f"deleted {file_path}"

        tool = Tool(
            name="delete_file",
            description="delete a file",
            function=delete_file,
            category=ToolCategory.SYSTEM,
            parameters={"file_path": {"type": "string"}},
            requires_confirmation=True,
        )
        executor = ToolExecutor(confirmation_callback=None)
        result = await executor.execute(tool, {"file_path": "test.txt"})

        assert result.success is False
        assert result.error_message is not None
        assert "denied" in result.error_message.lower() or "confirm" in result.error_message.lower()


# ---------------------------------------------------------------------------
# DR-03 — APScheduler shutdown(wait=True)
# ---------------------------------------------------------------------------


class TestAPSchedulerShutdownConfig:
    """server.py must use wait=True for APScheduler shutdown."""

    def test_scheduler_uses_wait_true(self):
        """Verify the runtime host calls scheduler.shutdown(wait=True)."""
        from pathlib import Path
        # The scheduler lifecycle moved out of the FastAPI lifespan into the
        # transport-agnostic RuntimeHost as part of the Telegram-first refactor.
        src = Path("src/runtime/host.py").read_text(encoding="utf-8")
        assert "shutdown(wait=True)" in src, (
            "DR-03: APScheduler must use shutdown(wait=True) to prevent dropping in-flight jobs"
        )
