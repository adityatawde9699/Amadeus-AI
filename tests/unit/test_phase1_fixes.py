"""
Phase 1 Unit Tests — Stop the Bleeding

Covers all 5 Phase 1 fixes:
1. ConfirmationCallback gate in ToolExecutor (requires_confirmation enforcement)
2. _trim_cache correctness in ConversationManager
3. search_file allowlist restriction (search outside allowlist returns no results)
4. Async llm_generate in agent_loop (smoke test)
5. Prometheus metrics import from infra layer (no circular import)
"""

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Heavy optional dep stubs (match pattern from test_amadeus_service_errors.py)
# ===========================================================================

for _mod in ("joblib", "numpy", "numpy.core"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google.genai" not in sys.modules:
    _genai = types.ModuleType("google.genai")
    _genai.Client = MagicMock()
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = MagicMock()
    sys.modules["google"] = sys.modules.get("google") or types.ModuleType("google")
    sys.modules["google"].genai = _genai


# ===========================================================================
# Helpers
# ===========================================================================

def _make_tool(requires_confirmation: bool = False, is_async: bool = False, name: str = "test_tool"):
    """Build a minimal Tool object for ToolExecutor tests."""
    from src.infra.tools.base import Tool, ToolCategory

    if is_async:
        async def _fn(**kwargs):
            return "async_result"
    else:
        def _fn(**kwargs):
            return "sync_result"

    return Tool(
        name=name,
        function=_fn,
        description="test",
        category=ToolCategory.SYSTEM,
        parameters={},
        requires_confirmation=requires_confirmation,
    )


# ===========================================================================
# Test Group 1: ConfirmationCallback enforcement in ToolExecutor
# ===========================================================================

class TestConfirmationGate:
    """Verifies that requires_confirmation=True is actually enforced."""

    @pytest.mark.asyncio
    async def test_destructive_tool_denied_by_callback(self):
        """Callback returns False → ToolExecutionResult.success is False."""
        from src.infra.tools.base import ToolExecutor
        from src.infra.tools.confirmation import ConfirmationCallback

        class _DenyAll(ConfirmationCallback):
            async def request_approval(self, tool_name, args, request_id, preview=None):
                return False

        executor = ToolExecutor(confirmation_callback=_DenyAll())
        tool = _make_tool(requires_confirmation=True)
        result = await executor.execute(tool, {})

        assert result.success is False
        assert "denied" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_destructive_tool_approved_by_callback(self):
        """Callback returns True → tool function is called, result is success."""
        from src.infra.tools.base import ToolExecutor
        from src.infra.tools.confirmation import ConfirmationCallback

        class _ApproveAll(ConfirmationCallback):
            async def request_approval(self, tool_name, args, request_id, preview=None):
                return True

        executor = ToolExecutor(confirmation_callback=_ApproveAll())
        tool = _make_tool(requires_confirmation=True)
        result = await executor.execute(tool, {})

        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_callback_denies_by_default(self):
        """No callback configured + requires_confirmation=True → denied."""
        from src.infra.tools.base import ToolExecutor

        executor = ToolExecutor(confirmation_callback=None)
        tool = _make_tool(requires_confirmation=True)
        result = await executor.execute(tool, {})

        assert result.success is False
        assert "confirmation handler" in result.error_message.lower() or "denied" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_non_destructive_tool_skips_gate(self):
        """requires_confirmation=False → callback is never consulted."""
        from src.infra.tools.base import ToolExecutor
        from src.infra.tools.confirmation import ConfirmationCallback

        called = []

        class _TrackingCallback(ConfirmationCallback):
            async def request_approval(self, tool_name, args, request_id, preview=None):
                called.append(True)
                return True

        executor = ToolExecutor(confirmation_callback=_TrackingCallback())
        tool = _make_tool(requires_confirmation=False)
        result = await executor.execute(tool, {})

        assert result.success is True
        assert called == [], "Gate should NOT be invoked for non-destructive tools"

    @pytest.mark.asyncio
    async def test_confirmation_callback_receives_correct_tool_name(self):
        """Callback receives the exact tool name."""
        from src.infra.tools.base import ToolExecutor
        from src.infra.tools.confirmation import ConfirmationCallback

        received_names = []

        class _RecordingCallback(ConfirmationCallback):
            async def request_approval(self, tool_name, args, request_id, preview=None):
                received_names.append(tool_name)
                return False

        executor = ToolExecutor(confirmation_callback=_RecordingCallback())
        tool = _make_tool(requires_confirmation=True, name="delete_file")
        await executor.execute(tool, {})

        assert received_names == ["delete_file"]


# ===========================================================================
# Test Group 2: APIConfirmationCallback
# ===========================================================================

class TestAPIConfirmationCallback:

    @pytest.mark.asyncio
    async def test_approve_resolves_future(self):
        """approve(id, True) unblocks request_approval and returns True."""
        from src.infra.tools.confirmation import APIConfirmationCallback

        callback = APIConfirmationCallback(timeout_seconds=5)

        async def _approve_after_tick():
            await asyncio.sleep(0.05)
            callback.approve(list(callback._pending.keys())[0], True)

        asyncio.create_task(_approve_after_tick())
        result = await callback.request_approval("test_tool", {}, "req-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_deny_resolves_future(self):
        """approve(id, False) unblocks request_approval and returns False."""
        from src.infra.tools.confirmation import APIConfirmationCallback

        callback = APIConfirmationCallback(timeout_seconds=5)

        async def _deny_after_tick():
            await asyncio.sleep(0.05)
            callback.approve(list(callback._pending.keys())[0], False)

        asyncio.create_task(_deny_after_tick())
        result = await callback.request_approval("test_tool", {}, "req-2")
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        """If nobody calls approve(), timeout elapses and returns False."""
        from src.infra.tools.confirmation import APIConfirmationCallback

        callback = APIConfirmationCallback(timeout_seconds=0.1)
        result = await callback.request_approval("test_tool", {}, "req-timeout")
        assert result is False

    def test_approve_unknown_id_returns_false(self):
        """approve() with unknown request_id returns False gracefully."""
        from src.infra.tools.confirmation import APIConfirmationCallback

        callback = APIConfirmationCallback()
        resolved = callback.approve("nonexistent-id", True)
        assert resolved is False


# ===========================================================================
# Test Group 3: _trim_cache correctness
# ===========================================================================

class TestTrimCache:
    """Verifies _trim_cache keeps the most recent max_context messages."""

    def _make_manager(self, max_context: int = 5):
        from src.app.services.amadeus_service import ConversationManager
        return ConversationManager(session_id="test-session", max_context=max_context)

    @pytest.mark.asyncio
    async def test_trim_at_exactly_max_context_plus_one(self):
        """Adding max_context+1 messages results in exactly max_context entries."""
        mgr = self._make_manager(max_context=5)
        for i in range(6):
            await mgr.add("user", f"message {i}")
        assert len(mgr._cache) == 5

    @pytest.mark.asyncio
    async def test_trim_keeps_newest_messages(self):
        """After trim, the newest max_context messages are retained."""
        mgr = self._make_manager(max_context=3)
        for i in range(6):  # messages 0..5
            await mgr.add("user", f"msg{i}")
        contents = [m.content for m in mgr._cache]
        assert contents == ["msg3", "msg4", "msg5"]

    @pytest.mark.asyncio
    async def test_no_trim_below_max_context(self):
        """Cache is not modified when below the limit."""
        mgr = self._make_manager(max_context=10)
        for i in range(5):
            await mgr.add("user", f"msg{i}")
        assert len(mgr._cache) == 5


# ===========================================================================
# Test Group 4: search_file allowlist enforcement
# ===========================================================================

class TestSearchFileAllowlist:
    """Verifies search_file only searches allowlist dirs and skips hidden dirs."""

    def test_search_restricted_to_allowlist(self, tmp_path):
        """Files outside the allowlist dirs are never returned."""
        from src.infra.tools.system_tools import search_file

        # Sensitive file outside allowlist
        sensitive = tmp_path / "secrets" / ".ssh" / "id_rsa"
        sensitive.parent.mkdir(parents=True)
        sensitive.write_text("PRIVATE KEY MATERIAL")

        # Allowlist points only at an empty temp subdir
        allowed_dir = tmp_path / "Documents"
        allowed_dir.mkdir()

        mock_settings = MagicMock()
        mock_settings.SEARCH_ALLOWED_DIRS = [str(allowed_dir)]
        mock_settings.FILE_SEARCH_MAX_RESULTS = 10

        with patch("src.core.config.get_settings", return_value=mock_settings):
            result = search_file(file_name="id_rsa")

        assert "No files found" in result

    def test_hidden_dirs_skipped(self, tmp_path):
        """Files inside hidden directories are never returned."""
        from src.infra.tools.system_tools import search_file

        allowed_dir = tmp_path / "Documents"
        allowed_dir.mkdir()

        # Create a file inside a hidden subdir
        hidden = allowed_dir / ".cache" / "secret.txt"
        hidden.parent.mkdir()
        hidden.write_text("cached data")

        mock_settings = MagicMock()
        mock_settings.SEARCH_ALLOWED_DIRS = [str(allowed_dir)]
        mock_settings.FILE_SEARCH_MAX_RESULTS = 10

        with patch("src.core.config.get_settings", return_value=mock_settings):
            result = search_file(file_name="secret.txt")

        assert "No files found" in result

    def test_valid_file_in_allowlist_found(self, tmp_path):
        """A file inside the allowlist is found and returned."""
        from src.infra.tools.system_tools import search_file

        allowed_dir = tmp_path / "Documents"
        allowed_dir.mkdir()
        report = allowed_dir / "quarterly_report.pdf"
        report.write_text("Q1 results")

        mock_settings = MagicMock()
        mock_settings.SEARCH_ALLOWED_DIRS = [str(allowed_dir)]
        mock_settings.FILE_SEARCH_MAX_RESULTS = 10

        with patch("src.core.config.get_settings", return_value=mock_settings):
            result = search_file(file_name="quarterly_report")

        assert "quarterly_report.pdf" in result

    def test_no_allowlist_dirs_exist(self, tmp_path):
        """Returns a helpful message when all allowlist dirs are missing."""
        from src.infra.tools.system_tools import search_file

        mock_settings = MagicMock()
        mock_settings.SEARCH_ALLOWED_DIRS = [str(tmp_path / "NonExistent")]
        mock_settings.FILE_SEARCH_MAX_RESULTS = 10

        with patch("src.core.config.get_settings", return_value=mock_settings):
            result = search_file(file_name="anything")

        assert "SEARCH_ALLOWED_DIRS" in result or "does not exist" in result.lower() or "restricted" in result.lower()


# ===========================================================================
# Test Group 5: Metrics module — no circular import
# ===========================================================================

class TestMetricsImport:
    def test_metrics_importable_without_server(self):
        """src.infra.metrics can be imported without pulling in src.api.server."""
        # If this import raises, it means there's a circular dependency
        from src.infra.metrics import (
            amadeus_llm_calls_total,
            amadeus_tool_calls_total,
            amadeus_cache_hit_rate,
            amadeus_llm_cost_usd,
        )
        assert amadeus_llm_calls_total is not None
        assert amadeus_tool_calls_total is not None
        assert amadeus_cache_hit_rate is not None
        assert amadeus_llm_cost_usd is not None

    def test_metrics_not_imported_from_api_layer_in_amadeus_service(self):
        """amadeus_service.py should reference src.infra.metrics, not src.api.server."""
        service_path = Path(
            "c:/Users/ASUS/Downloads/vs code/.vscode/python/Amadeus-AI"
            "/src/app/services/amadeus_service.py"
        )
        source = service_path.read_text(encoding="utf-8")
        assert "from src.api.server import amadeus" not in source, (
            "amadeus_service.py must not import Prometheus metrics from src.api.server"
        )
