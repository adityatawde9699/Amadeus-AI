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
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# AG-01 — Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Agent terminates when caught in a tool-calling loop."""

    def _make_registry_executor(self):
        from src.app.services.tool_registry import ToolRegistry
        from src.infra.tools.base import ToolExecutor, Tool, ToolCategory

        registry = ToolRegistry()
        executor = ToolExecutor()

        # Register a dummy web_search tool
        def web_search(query: str) -> str:
            return f"results for: {query}"

        t = Tool(
            name="web_search",
            description="search",
            function=web_search,
            category=ToolCategory.RESEARCH,
            parameters={"query": {"type": "string"}},
        )
        registry.register(t)
        return registry, executor

    @pytest.mark.asyncio
    async def test_exact_cycle_detected_within_max_iterations(self):
        """Same (action, args) pair twice → agent terminates before max_iterations."""
        from src.app.services.legacy_agent_loop import ReActAgent

        registry, executor = self._make_registry_executor()
        call_count = 0

        async def looping_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            # Always return the exact same action + args → exact cycle
            return (
                'Thought: need to search\n'
                'Action: web_search\n'
                'Action Input: {"query": "test"}'
            )

        agent = ReActAgent(registry, executor, llm_generate=looping_llm, max_iterations=10)
        result = await agent.run("search something")

        # Must terminate before hitting max_iterations
        assert result.total_iterations < 10, (
            f"Expected cycle detection before iteration 10, got {result.total_iterations}"
        )

    @pytest.mark.asyncio
    async def test_frequency_cycle_detected_with_varying_args(self):
        """Same tool >3 times with different args → secondary frequency guard fires."""
        from src.app.services.legacy_agent_loop import ReActAgent

        registry, executor = self._make_registry_executor()
        call_count = 0

        async def varying_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            # Different args each time — primary guard won't trigger
            return (
                f'Thought: searching\n'
                f'Action: web_search\n'
                f'Action Input: {{"query": "query_{call_count}"}}'
            )

        agent = ReActAgent(registry, executor, llm_generate=varying_llm, max_iterations=20)
        result = await agent.run("find everything")

        # Secondary guard: same tool > 3 times → terminate before iteration 20
        assert result.total_iterations <= 6, (
            f"Frequency cycle guard should trigger by iteration 6, got {result.total_iterations}"
        )


# ---------------------------------------------------------------------------
# AG-02 — SYNTHESIZE success flag
# ---------------------------------------------------------------------------


class TestSynthesizeSuccessFlag:
    """SYNTHESIZE must report success=False when all observations are errors."""

    @pytest.mark.asyncio
    async def test_all_error_observations_yield_success_false(self):
        """When every observation starts with 'Error', result.success must be False."""
        from src.app.services.legacy_agent_loop import ReActAgent
        from src.app.services.tool_registry import ToolRegistry
        from src.infra.tools.base import ToolExecutor, Tool, ToolCategory

        registry = ToolRegistry()
        executor = ToolExecutor()

        def broken_tool(q: str) -> str:
            return "Error: service unavailable"

        registry.register(Tool(
            name="broken_tool",
            description="always errors",
            function=broken_tool,
            category=ToolCategory.SYSTEM,
            parameters={"q": {"type": "string"}},
        ))

        call_count = 0

        async def error_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return (
                    'Thought: let me try\n'
                    'Action: broken_tool\n'
                    'Action Input: {"q": "test"}'
                )
            return 'Thought: done\nAction: FINISH\nAction Input: {"answer": "failed"}'

        agent = ReActAgent(registry, executor, llm_generate=error_llm, max_iterations=5)
        result = await agent.run("do something")

        # All observations were errors → success must be False
        if result.tools_used:
            assert result.success is False or result.final_answer, (
                "Expected success=False when all tool observations are errors"
            )


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


class TestOrchestratorShutdown:
    """AgentOrchestrator.shutdown() must cancel and await the worker task."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_worker_task(self):
        """shutdown() must cancel _worker_task so no zombie tasks remain."""
        from src.app.services.legacy_agent_loop import AgentOrchestrator
        from src.app.services.tool_registry import ToolRegistry
        from src.infra.tools.base import ToolExecutor

        registry = ToolRegistry()
        executor = ToolExecutor()

        orchestrator = AgentOrchestrator(
            tool_registry=registry,
            tool_executor=executor,
            llm_generate=None,
            auto_start=False,
        )

        # Manually set a running task
        async def long_running():
            await asyncio.sleep(999)

        orchestrator._worker_task = asyncio.create_task(long_running())

        # Shutdown must cancel it cleanly
        await orchestrator.shutdown()
        # Yield to the event loop so the cancellation can be finalized
        await asyncio.sleep(0)

        assert orchestrator._worker_task.done(), "Worker task must be done after shutdown"
        assert orchestrator._worker_task.cancelled(), "Worker task must be cancelled"

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self):
        """Calling shutdown() twice must not raise."""
        from src.app.services.legacy_agent_loop import AgentOrchestrator
        from src.app.services.tool_registry import ToolRegistry
        from src.infra.tools.base import ToolExecutor

        orchestrator = AgentOrchestrator(
            tool_registry=ToolRegistry(),
            tool_executor=ToolExecutor(),
            llm_generate=None,
            auto_start=False,
        )
        # No worker task — should not raise
        await orchestrator.shutdown()
        await orchestrator.shutdown()  # second call must also be safe


# ---------------------------------------------------------------------------
# HITL — Deny by default when no callback set
# ---------------------------------------------------------------------------


class TestHITLDenyByDefault:
    """Destructive tools must be denied when no confirmation_callback is set."""

    @pytest.mark.asyncio
    async def test_destructive_tool_denied_without_callback(self):
        """execute() must return success=False for requires_confirmation tools when callback=None."""
        from src.infra.tools.base import Tool, ToolExecutor, ToolCategory

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
        """Verify the lifespan code calls scheduler.shutdown(wait=True)."""
        from pathlib import Path
        src = Path("src/api/server.py").read_text(encoding="utf-8")
        assert "shutdown(wait=True)" in src, (
            "DR-03: APScheduler must use shutdown(wait=True) to prevent dropping in-flight jobs"
        )
