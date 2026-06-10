"""
Tests for the Telegram-first 30-day roadmap changes:

  - Feature-flag defaults on Settings (WS-A): optional/high-risk subsystems are
    off by default; behaviour-preserving flags stay on.
  - Telegram daemon (WS-D): refuses to start without TELEGRAM_BOT_TOKEN /
    MASTER_TELEGRAM_CHAT_ID, and skips migrations by default.

Telegram authorization and tool-policy gating are already covered by
``test_security_hardening.py`` and ``test_tool_policy.py`` respectively.
"""

from __future__ import annotations

import pytest

from src.core.config import Settings, get_settings
from src.transports import telegram_daemon as daemon


class TestFeatureFlagDefaults:
    """The default local runtime must stay small and safe."""

    @pytest.mark.parametrize(
        "flag",
        [
            "SLM_WARMUP_ON_START",
            "ENABLE_EMAIL",
            "ENABLE_MCP",
            "ENABLE_DOCKER_SANDBOX",
            "ENABLE_PLUGINS",
            "ENABLE_PROACTIVE_LOOP",
            "ENABLE_AUTONOMOUS_LOOP",
        ],
    )
    def test_optional_subsystems_default_off(self, flag: str) -> None:
        assert Settings.model_fields[flag].default is False, (
            f"{flag} must default to False so it is opt-in"
        )

    @pytest.mark.parametrize(
        "flag",
        ["ENABLE_API", "ENABLE_SYSTEM_TOOLS", "RUN_MIGRATIONS_ON_START"],
    )
    def test_behaviour_preserving_flags_default_on(self, flag: str) -> None:
        assert Settings.model_fields[flag].default is True, (
            f"{flag} must default to True to preserve existing FastAPI behaviour"
        )


class TestDaemonRequiredSettings:
    """The daemon is useless without a bot token and an authorized chat."""

    def test_missing_both_are_reported(self) -> None:
        s = get_settings().model_copy(
            update={"TELEGRAM_BOT_TOKEN": None, "MASTER_TELEGRAM_CHAT_ID": None}
        )
        assert daemon._check_required_settings(s) == [
            "TELEGRAM_BOT_TOKEN",
            "MASTER_TELEGRAM_CHAT_ID",
        ]

    def test_present_settings_pass(self) -> None:
        s = get_settings().model_copy(
            update={"TELEGRAM_BOT_TOKEN": "token", "MASTER_TELEGRAM_CHAT_ID": "123"}
        )
        assert daemon._check_required_settings(s) == []

    def test_main_exits_nonzero_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = get_settings().model_copy(
            update={"TELEGRAM_BOT_TOKEN": None, "MASTER_TELEGRAM_CHAT_ID": None}
        )
        monkeypatch.setattr(daemon, "get_settings", lambda: s)
        with pytest.raises(SystemExit) as exc:
            daemon.main()
        assert exc.value.code == 2


class TestDaemonPrepareSettings:
    """The daemon starts lightweight: no Alembic on every boot by default."""

    def test_skips_migrations_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RUN_MIGRATIONS_ON_START", raising=False)
        s = get_settings().model_copy(update={"RUN_MIGRATIONS_ON_START": True})
        assert daemon._prepare_settings(s).RUN_MIGRATIONS_ON_START is False

    def test_respects_explicit_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RUN_MIGRATIONS_ON_START", "true")
        s = get_settings().model_copy(update={"RUN_MIGRATIONS_ON_START": True})
        assert daemon._prepare_settings(s).RUN_MIGRATIONS_ON_START is True
