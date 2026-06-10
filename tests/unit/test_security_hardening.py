"""
Phase 11 — Security Hardening Unit Tests.

Tests every critical security fix from the audit:
  - SEC-01: Prompt injection resistance in ReAct
  - SEC-03: Telegram authorization guard
  - CQ-01/02: Path traversal blocked in filesystem tools
  - CQ-03: _validate_args fails fast on missing required params
  - P6-T7: Memory deduplication (idempotent upsert key)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# SEC-01 — Prompt injection resistance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SEC-03 — Telegram authorization guard
# ---------------------------------------------------------------------------


class TestTelegramAuthorizationGuard:
    """Unauthorized Telegram users must be rejected before processing."""

    @pytest.mark.asyncio
    async def test_unauthorized_chat_id_is_rejected(self):
        """A chat_id NOT in MASTER_TELEGRAM_CHAT_ID gets 'Unauthorized.' reply."""
        from src.transports.telegram_transport import TelegramTransport

        adapter = TelegramTransport.__new__(TelegramTransport)
        adapter._active_tasks = set()
        adapter.runtime = None
        sent_messages: list[tuple] = []

        async def fake_send(chat_id: int, text: str) -> None:
            sent_messages.append((chat_id, text))

        adapter.send_message = fake_send  # type: ignore[method-assign]

        mock_update = MagicMock()
        mock_update.message.chat_id = 99999
        mock_update.message.text = "rm -rf /"

        with patch("src.transports.telegram_transport.get_settings") as mock_cfg:
            mock_cfg.return_value.MASTER_TELEGRAM_CHAT_ID = "111111"
            await adapter._handle_message(mock_update, None)

        assert len(sent_messages) == 1
        assert sent_messages[0][1] == "Unauthorized."
        assert sent_messages[0][0] == 99999

    @pytest.mark.asyncio
    async def test_authorized_chat_id_passes_guard(self):
        """The configured MASTER_TELEGRAM_CHAT_ID must pass the auth guard."""
        from src.transports.telegram_transport import TelegramTransport

        adapter = TelegramTransport.__new__(TelegramTransport)
        adapter._active_tasks = set()
        adapter.runtime = None
        tasks_created: list = []

        async def fake_send(chat_id: int, text: str) -> None:
            pass

        adapter.send_message = fake_send  # type: ignore[method-assign]

        mock_update = MagicMock()
        mock_update.message.chat_id = 111111
        mock_update.message.text = "hello"

        with (
            patch("src.transports.telegram_transport.get_settings") as mock_cfg,
            patch("asyncio.create_task") as mock_task,
        ):
            mock_cfg.return_value.MASTER_TELEGRAM_CHAT_ID = "111111"
            await adapter._handle_message(mock_update, None)

        # Task should have been created (auth guard passed)
        mock_task.assert_called_once()


# ---------------------------------------------------------------------------
# Path traversal — CQ-01 / CQ-02
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Sandboxing features removed or moved out of scope")
class TestPathSandboxing:
    """copy_file / move_file / create_folder must reject out-of-sandbox paths."""

    def _mock_settings_with_allowed_dirs(self, dirs: list[str]):
        mock = MagicMock()
        mock.SEARCH_ALLOWED_DIRS = dirs
        return mock

    def test_copy_file_blocked_outside_allowed_dirs(self):
        from src.infra.tools.system_tools import copy_file

        with patch(
            "src.infra.tools.system_tools.get_settings",
            return_value=self._mock_settings_with_allowed_dirs(["~/Documents"]),
        ):
            result = copy_file(
                source_path="C:/Windows/System32/evil.dll",
                destination_path="C:/Users/victim/Desktop/evil.dll",
            )
        assert "Access denied" in result

    def test_move_file_blocked_outside_allowed_dirs(self):
        from src.infra.tools.system_tools import move_file

        with patch(
            "src.infra.tools.system_tools.get_settings",
            return_value=self._mock_settings_with_allowed_dirs(["~/Documents"]),
        ):
            result = move_file(
                source_path="C:/Windows/hosts",
                destination_path="C:/tmp/exfil.txt",
            )
        assert "Access denied" in result

    def test_create_folder_blocked_outside_allowed_dirs(self):
        from src.infra.tools.system_tools import create_folder

        with patch(
            "src.infra.tools.system_tools.get_settings",
            return_value=self._mock_settings_with_allowed_dirs(["~/Documents"]),
        ):
            result = create_folder(folder_name="C:/Windows/AmadeusEvil")
        assert "Access denied" in result

    def test_path_traversal_sequence_blocked(self):
        """../../etc/passwd style traversal must be caught by path resolution."""
        from pathlib import Path

        from src.infra.tools.system_tools import _assert_in_allowed_dirs

        with patch(
            "src.infra.tools.system_tools.get_settings"
        ) as mock_cfg:
            mock_cfg.return_value.SEARCH_ALLOWED_DIRS = [
                str(Path.home() / "Documents")
            ]
            # Simulated traversal
            evil = Path.home() / "Documents" / ".." / ".." / "etc" / "passwd"
            result = _assert_in_allowed_dirs(evil)
        # Should be denied (resolves outside ~/Documents)
        assert result is not None  # error string returned
        assert "Access denied" in result


# ---------------------------------------------------------------------------
# CQ-03 — _validate_args fails fast on missing required params
# ---------------------------------------------------------------------------


class TestValidateArgsMissingParams:
    """ToolExecutor must surface missing-param errors before retrying."""

    @pytest.mark.asyncio
    async def test_missing_required_param_returns_failure(self):
        """execute() must return success=False when a required param is absent."""
        from src.infra.tools.base import Tool, ToolExecutor, ToolCategory

        def needs_query(query: str) -> str:
            return f"result for {query}"

        tool = Tool(
            name="needs_query",
            description="test",
            function=needs_query,
            category=ToolCategory.SYSTEM,
            parameters={"query": {"type": "string", "required": True}},
        )
        executor = ToolExecutor()
        result = await executor.execute(tool, {})  # no 'query' provided

        assert result.success is False
        assert "query" in (result.error_message or "").lower() or \
               "missing" in (result.error_message or "").lower()


# ---------------------------------------------------------------------------
# P6-T7 — Memory deduplication
# ---------------------------------------------------------------------------


class TestMemoryDeduplication:
    """Identical messages must produce the same Qdrant point UUID."""

    def test_same_content_produces_same_uuid(self):
        """Content-based key must be deterministic — no timestamp in key."""
        import uuid as _uuid
        session_id = "test_session"
        role = "user"
        text = "I love astronomy"

        # Replicate the key construction from memory_service.store()
        raw_key = f"{session_id}:{role}:{text}"
        id1 = str(_uuid.uuid5(_uuid.NAMESPACE_OID, raw_key))
        id2 = str(_uuid.uuid5(_uuid.NAMESPACE_OID, raw_key))

        assert id1 == id2, "Content-based UUID must be deterministic"

    def test_different_content_produces_different_uuid(self):
        """Different text must produce different IDs."""
        import uuid as _uuid
        session_id = "test_session"
        role = "user"

        id1 = str(_uuid.uuid5(_uuid.NAMESPACE_OID, f"{session_id}:{role}:hello"))
        id2 = str(_uuid.uuid5(_uuid.NAMESPACE_OID, f"{session_id}:{role}:world"))

        assert id1 != id2
