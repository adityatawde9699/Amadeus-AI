"""
Unit tests for the Telegram-first daemon (src/transports/telegram_daemon.py)
and the supporting runtime components it owns.

All external I/O (DB, Telegram API, Redis, filesystem) is mocked so these
tests run offline with no infrastructure.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import Settings
from src.transports import telegram_daemon as daemon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = {
        "SKIP_CONFIG_VALIDATION": True,
        "TELEGRAM_BOT_TOKEN": "token123",
        "MASTER_TELEGRAM_CHAT_ID": "111",
        "DATABASE_URL": "sqlite+aiosqlite:///./test.db",
    }
    base.update(overrides)
    return Settings(**base)


# ===========================================================================
# _check_required_settings
# ===========================================================================


class TestCheckRequiredSettings:
    def test_missing_both(self):
        s = _settings(TELEGRAM_BOT_TOKEN=None, MASTER_TELEGRAM_CHAT_ID=None)
        assert daemon._check_required_settings(s) == [
            "TELEGRAM_BOT_TOKEN",
            "MASTER_TELEGRAM_CHAT_ID",
        ]

    def test_missing_token_only(self):
        s = _settings(TELEGRAM_BOT_TOKEN=None)
        missing = daemon._check_required_settings(s)
        assert "TELEGRAM_BOT_TOKEN" in missing
        assert "MASTER_TELEGRAM_CHAT_ID" not in missing

    def test_missing_chat_id_only(self):
        s = _settings(MASTER_TELEGRAM_CHAT_ID=None)
        missing = daemon._check_required_settings(s)
        assert "MASTER_TELEGRAM_CHAT_ID" in missing
        assert "TELEGRAM_BOT_TOKEN" not in missing

    def test_all_present_returns_empty(self):
        s = _settings()
        assert daemon._check_required_settings(s) == []


# ===========================================================================
# _prepare_settings
# ===========================================================================


class TestPrepareSettings:
    def test_disables_migrations_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("RUN_MIGRATIONS_ON_START", raising=False)
        s = _settings(RUN_MIGRATIONS_ON_START=True)
        result = daemon._prepare_settings(s)
        assert result.RUN_MIGRATIONS_ON_START is False

    def test_disables_api_always(self, monkeypatch):
        monkeypatch.delenv("RUN_MIGRATIONS_ON_START", raising=False)
        s = _settings(ENABLE_API=True)
        result = daemon._prepare_settings(s)
        assert result.ENABLE_API is False

    def test_respects_explicit_env_opt_in(self, monkeypatch):
        monkeypatch.setenv("RUN_MIGRATIONS_ON_START", "true")
        s = _settings(RUN_MIGRATIONS_ON_START=True)
        result = daemon._prepare_settings(s)
        assert result.RUN_MIGRATIONS_ON_START is True

    def test_returns_same_settings_when_no_overrides_needed(self, monkeypatch):
        monkeypatch.setenv("RUN_MIGRATIONS_ON_START", "true")
        s = _settings(RUN_MIGRATIONS_ON_START=True, ENABLE_API=False)
        result = daemon._prepare_settings(s)
        # ENABLE_API was already False — still ends up False
        assert result.ENABLE_API is False


# ===========================================================================
# _write_pid_file / _remove_pid_file
# ===========================================================================


class TestPidFile:
    def test_write_creates_file_with_pid(self, tmp_path):
        s = _settings(DATA_DIR=str(tmp_path))
        pid_path = daemon._write_pid_file(s)
        assert pid_path is not None
        assert pid_path.exists()
        assert pid_path.read_text().strip() == str(os.getpid())

    def test_remove_deletes_file(self, tmp_path):
        pid_path = tmp_path / "amadeus-daemon.pid"
        pid_path.write_text("12345")
        daemon._remove_pid_file(pid_path)
        assert not pid_path.exists()

    def test_remove_none_is_safe(self):
        # Should not raise
        daemon._remove_pid_file(None)

    def test_write_non_existent_parent_created(self, tmp_path):
        nested = tmp_path / "sub" / "dir"
        s = _settings(DATA_DIR=str(nested))
        pid_path = daemon._write_pid_file(s)
        assert pid_path is not None
        assert pid_path.exists()


# ===========================================================================
# main() — entry point guards
# ===========================================================================


class TestMain:
    def test_exits_2_when_token_missing(self, monkeypatch):
        s = _settings(TELEGRAM_BOT_TOKEN=None, MASTER_TELEGRAM_CHAT_ID=None)
        monkeypatch.setattr(daemon, "get_settings", lambda: s)
        with pytest.raises(SystemExit) as exc_info:
            daemon.main()
        assert exc_info.value.code == 2

    def test_exits_2_when_chat_id_missing(self, monkeypatch):
        s = _settings(MASTER_TELEGRAM_CHAT_ID=None)
        monkeypatch.setattr(daemon, "get_settings", lambda: s)
        with pytest.raises(SystemExit) as exc_info:
            daemon.main()
        assert exc_info.value.code == 2

    def test_runs_when_settings_ok(self, monkeypatch, tmp_path):
        """main() should call asyncio.run(_run(...)) when settings are valid."""
        s = _settings(DATA_DIR=str(tmp_path))
        monkeypatch.setattr(daemon, "get_settings", lambda: s)

        async def _fake_run(_settings):
            pass  # succeed immediately

        monkeypatch.setattr(daemon, "_run", _fake_run)
        # Should not raise
        daemon.main()

    def test_keyboard_interrupt_exits_cleanly(self, monkeypatch, tmp_path):
        s = _settings(DATA_DIR=str(tmp_path))
        monkeypatch.setattr(daemon, "get_settings", lambda: s)

        async def _raise(_):
            raise KeyboardInterrupt

        monkeypatch.setattr(daemon, "_run", _raise)
        # Should not propagate the interrupt
        daemon.main()


# ===========================================================================
# _run() — startup retry behaviour
# ===========================================================================


class TestRunStartupRetries:
    @pytest.mark.asyncio
    async def test_retries_on_transient_start_failure(self, monkeypatch, tmp_path):
        """_run() should retry RuntimeHost.start() up to DAEMON_MAX_START_RETRIES."""
        s = _settings(DATA_DIR=str(tmp_path))
        monkeypatch.setenv("DAEMON_MAX_START_RETRIES", "2")

        call_count = 0
        stopped = False
        stop_event = asyncio.Event()

        class FakeHost:
            async def start(self):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise ConnectionError("DB not ready")
                # Second attempt succeeds: signal stop
                stop_event.set()

            async def stop(self):
                nonlocal stopped
                stopped = True

            telegram = None

        monkeypatch.setattr(daemon, "RuntimeHost", lambda settings: FakeHost())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        await daemon._run(s, stop_event=stop_event)

        assert call_count == 2
        assert stopped is True

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self, monkeypatch, tmp_path):
        """_run() should raise after exhausting retries."""
        s = _settings(DATA_DIR=str(tmp_path))
        monkeypatch.setenv("DAEMON_MAX_START_RETRIES", "2")

        class AlwaysFailHost:
            async def start(self):
                raise RuntimeError("DB permanently down")

            async def stop(self):
                pass

        monkeypatch.setattr(daemon, "RuntimeHost", lambda settings: AlwaysFailHost())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        with pytest.raises(RuntimeError, match="DB permanently down"):
            await daemon._run(s)


# ===========================================================================
# DependencyWatchdog
# ===========================================================================


class TestDependencyWatchdog:
    def test_stop_sets_event(self):
        from src.infra.resilience.watchdog import DependencyWatchdog

        s = _settings()
        wd = DependencyWatchdog(s)
        assert not wd._stop_event.is_set()
        wd.stop()
        assert wd._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_run_stops_promptly_on_stop(self):
        from src.infra.resilience.watchdog import DependencyWatchdog

        s = _settings()
        wd = DependencyWatchdog(s)

        # _check_all does nothing (Redis URL not set, MEMORY_ENABLED may be True)
        task = asyncio.create_task(wd.run(interval_seconds=60))
        await asyncio.sleep(0)  # let the loop start
        wd.stop()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            task.cancel()
            pytest.fail("DependencyWatchdog did not stop within 2 s")

    @pytest.mark.asyncio
    async def test_redis_check_returns_false_when_no_url(self):
        from src.infra.resilience.watchdog import DependencyWatchdog

        s = _settings(REDIS_URL="")
        wd = DependencyWatchdog(s)
        result = await wd.check_redis()
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_check_returns_false_on_connection_error(self):
        from src.infra.resilience.watchdog import DependencyWatchdog

        s = _settings(REDIS_URL="redis://nonexistent-host:9999/0")
        wd = DependencyWatchdog(s)
        # Should return False gracefully, not raise
        result = await wd.check_redis()
        assert result is False

    @pytest.mark.asyncio
    async def test_emits_event_on_redis_state_change(self):
        from src.infra.resilience.watchdog import DependencyWatchdog
        from src.runtime.events import EventBus

        s = _settings(REDIS_URL="redis://nonexistent:9999/0")
        bus = EventBus()
        emitted: list[tuple] = []

        @bus.on("provider.disabled")
        async def _on_disabled(payload):
            emitted.append(("disabled", payload))

        wd = DependencyWatchdog(s, event_bus=bus)
        wd.dependencies["redis"] = True  # pretend it was up

        await wd._check_all()

        # Redis check should fail → state change → event emitted
        assert any(kind == "disabled" for kind, _ in emitted)


# ===========================================================================
# EventBus
# ===========================================================================


class TestEventBus:
    @pytest.mark.asyncio
    async def test_emit_calls_sync_handler(self):
        from src.runtime.events import EventBus

        bus = EventBus()
        received = []
        bus.on("test.event", received.append)
        await bus.emit("test.event", {"key": "value"})
        assert received == [{"key": "value"}]

    @pytest.mark.asyncio
    async def test_emit_calls_async_handler(self):
        from src.runtime.events import EventBus

        bus = EventBus()
        received = []

        async def handler(p):
            received.append(p)

        bus.on("test.event", handler)
        await bus.emit("test.event", {"key": "async"})
        assert received == [{"key": "async"}]

    @pytest.mark.asyncio
    async def test_emit_no_handlers_does_not_raise(self):
        from src.runtime.events import EventBus

        bus = EventBus()
        await bus.emit("no.one.listening", {})

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_propagate(self):
        from src.runtime.events import EventBus

        bus = EventBus()

        def bad_handler(_):
            raise ValueError("boom")

        bus.on("test", bad_handler)
        # Should not raise
        await bus.emit("test", {})

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self):
        from src.runtime.events import EventBus

        bus = EventBus()
        log = []
        bus.on("x", lambda _: log.append(1))
        bus.on("x", lambda _: log.append(2))
        await bus.emit("x", {})
        assert sorted(log) == [1, 2]


# ===========================================================================
# TaskScheduler — start/stop guards
# ===========================================================================


class TestTaskSchedulerGuards:
    @pytest.mark.asyncio
    async def test_start_twice_does_not_create_second_sweeper(self):
        from src.runtime.scheduler import TaskScheduler

        sched = TaskScheduler(poll_interval_seconds=999)
        dispatch = AsyncMock()

        with (
            patch("src.runtime.scheduler.get_session"),
            patch("src.runtime.scheduler.ScheduledTaskRepository") as MockRepo,
        ):
            MockRepo.return_value.requeue_stuck_running = AsyncMock(return_value=0)
            MockRepo.return_value.claim_due = AsyncMock(return_value=[])

            await sched.start(dispatch)
            first_sweeper = sched._sweeper
            await sched.start(dispatch)  # second call
            assert sched._sweeper is first_sweeper  # same task

        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_sweeper(self):
        from src.runtime.scheduler import TaskScheduler

        sched = TaskScheduler(poll_interval_seconds=999)
        dispatch = AsyncMock()

        with (
            patch("src.runtime.scheduler.get_session"),
            patch("src.runtime.scheduler.ScheduledTaskRepository") as MockRepo,
        ):
            MockRepo.return_value.requeue_stuck_running = AsyncMock(return_value=0)
            MockRepo.return_value.claim_due = AsyncMock(return_value=[])

            await sched.start(dispatch)
            assert sched._sweeper is not None
            await sched.stop()
            assert sched._sweeper is None
