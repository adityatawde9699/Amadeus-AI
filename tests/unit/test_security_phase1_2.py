"""
Security regression tests for remediation Phase 1 & 2.

Covers:
  * Telegram allowlist parsing (fail closed) + startup validation
  * Public registration field stripping (no self-service role/tenant)
  * Sandbox fail-closed (disabled default; no in-process execution)
  * Graduated permission profiles + role mapping
  * min_permission authorization boundary in the executor
  * execute() least-privilege default (no implicit SYSTEM_FULL)
  * request-scoped, owner-aware confirmation callbacks
"""

from __future__ import annotations

import pytest

from src.core.config import Settings, validate_settings
from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile, profile_for_role


# =============================================================================
# Phase 1.1 — Telegram allowlist (fail closed)
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "expected_valid"),
    [
        (None, False),       # missing
        ("", False),         # empty
        ("   ", False),      # whitespace
        ("abc", False),      # malformed
        ("123,abc", False),  # mixed-invalid → whole list invalid (fail closed)
        ("123", True),
        ("123, 456 ,789", True),
    ],
)
def test_telegram_allowlist_parsing(raw, expected_valid):
    s = Settings(MASTER_TELEGRAM_CHAT_ID=raw, SKIP_CONFIG_VALIDATION=True)
    ids, valid = s.parse_telegram_allowlist()
    assert valid is expected_valid
    if not valid:
        assert ids == frozenset()


def test_validate_settings_requires_allowlist_with_token():
    # Dev: warning only.
    dev = Settings(ENV="development", TELEGRAM_BOT_TOKEN="x", MASTER_TELEGRAM_CHAT_ID=None,
                   SKIP_CONFIG_VALIDATION=True)
    report = validate_settings(dev)
    assert any("MASTER_TELEGRAM_CHAT_ID" in w for w in report["warnings"])

    # Production: hard error (fail closed).
    prod = Settings(ENV="production", TELEGRAM_BOT_TOKEN="x", MASTER_TELEGRAM_CHAT_ID="",
                    SECRET_KEY="k" * 32, GEMINI_API_KEY="g", SKIP_CONFIG_VALIDATION=True)
    report = validate_settings(prod)
    assert any("MASTER_TELEGRAM_CHAT_ID" in e for e in report["errors"])
    assert report["valid"] is False


def test_telegram_elevated_ids_subset():
    s = Settings(TELEGRAM_ELEVATED_CHAT_IDS="42, 99", SKIP_CONFIG_VALIDATION=True)
    assert s.telegram_elevated_ids() == frozenset({42, 99})
    # Malformed → empty (no implicit elevation).
    s2 = Settings(TELEGRAM_ELEVATED_CHAT_IDS="42,bad", SKIP_CONFIG_VALIDATION=True)
    assert s2.telegram_elevated_ids() == frozenset()


# =============================================================================
# Phase 1.2 — Public registration lockdown
# =============================================================================


def test_user_create_rejects_role_and_tenant():
    from src.api.auth.schemas import UserCreate, UserUpdate

    assert "role" not in UserCreate.model_fields
    assert "tenant_id" not in UserCreate.model_fields
    assert "role" not in UserUpdate.model_fields
    assert "tenant_id" not in UserUpdate.model_fields

    # Even if a client sends role=admin, the model drops it (extra ignored).
    u = UserCreate(email="a@b.com", password="pw", username="bob", role="admin")
    dumped = u.create_update_dict()
    assert "role" not in dumped
    assert "tenant_id" not in dumped


# =============================================================================
# Phase 1.3 — Sandbox fail closed
# =============================================================================


def test_sandbox_mode_default_disabled():
    s = Settings(SKIP_CONFIG_VALIDATION=True)
    assert s.SANDBOX_MODE == "disabled"


def test_get_sandbox_raises_when_disabled(monkeypatch):
    import src.core.config as cfg
    import src.infra.tools.developer_tools as dt

    monkeypatch.setattr(dt, "_sandbox", None)
    monkeypatch.setattr(
        cfg, "get_settings", lambda: Settings(SANDBOX_MODE="disabled", SKIP_CONFIG_VALIDATION=True)
    )
    with pytest.raises(dt.SandboxUnavailableError):
        dt._get_sandbox()


@pytest.mark.asyncio
async def test_execute_python_script_fails_closed_when_disabled(monkeypatch):
    import src.core.config as cfg
    import src.infra.tools.developer_tools as dt

    monkeypatch.setattr(dt, "_sandbox", None)
    monkeypatch.setattr(
        cfg, "get_settings", lambda: Settings(SANDBOX_MODE="disabled", SKIP_CONFIG_VALIDATION=True)
    )
    fn = dt.execute_python_script._tool_metadata.function
    out = fn(code="import os; os.system('id')")
    assert "unavailable" in out.lower()
    # Crucially, it must NOT have executed anything.
    assert "uid=" not in out


def test_local_sandbox_executor_is_gone():
    import importlib

    with pytest.raises(ImportError):
        importlib.import_module("src.infra.sandbox.local_executor")


# =============================================================================
# Phase 2.1 — Profiles + role mapping
# =============================================================================


def test_profile_rank_and_mapping():
    assert PermissionProfile.READ_ONLY.rank < PermissionProfile.STANDARD.rank
    assert PermissionProfile.STANDARD.rank < PermissionProfile.SYSTEM_FULL.rank
    assert profile_for_role("admin") is PermissionProfile.SYSTEM_FULL
    assert profile_for_role("user") is PermissionProfile.STANDARD
    assert profile_for_role("guest") is PermissionProfile.READ_ONLY
    assert profile_for_role(None) is PermissionProfile.READ_ONLY
    assert profile_for_role("nonsense") is PermissionProfile.READ_ONLY
    assert PermissionProfile.STANDARD.satisfies(PermissionProfile.READ_ONLY)
    assert not PermissionProfile.STANDARD.satisfies(PermissionProfile.SYSTEM_FULL)


# =============================================================================
# Phase 2.2 / 2.3 — Executor authorization boundary + least privilege
# =============================================================================


def _make_tool(name, category, requires_confirmation=False):
    from src.infra.tools.base import ToolCategory, tool

    @tool(name=name, description="d", category=getattr(ToolCategory, category),
          parameters={}, requires_confirmation=requires_confirmation)
    async def _fn(**kwargs):
        return "ran"

    return _fn._tool_metadata


def _ctx(profile, session_id="s"):
    return RequestContext(request_id="r", session_id=session_id, user_id="u", permissions=profile)


@pytest.mark.asyncio
async def test_executor_denies_below_min_permission():
    from src.infra.tools.base import ToolExecutor

    ex = ToolExecutor()
    dev_tool = _make_tool("danger_dev", "DEVELOPER")  # auto min = system_full

    denied = await ex.execute(dev_tool, {}, context=_ctx(PermissionProfile.STANDARD))
    assert denied.success is False
    assert "security policy" in (denied.error_message or "").lower()


@pytest.mark.asyncio
async def test_executor_defaults_to_read_only():
    """No context and no profile must NOT grant SYSTEM_FULL."""
    from src.infra.tools.base import ToolExecutor

    ex = ToolExecutor()
    dev_tool = _make_tool("danger_dev2", "DEVELOPER")  # requires system_full

    denied = await ex.execute(dev_tool, {})  # no profile/context → READ_ONLY
    assert denied.success is False
    assert "security policy" in (denied.error_message or "").lower()


@pytest.mark.asyncio
async def test_executor_allows_read_only_tool_for_standard():
    from src.infra.tools.base import ToolExecutor

    ex = ToolExecutor()
    info_tool = _make_tool("safe_info", "MONITORING")  # auto min = read_only

    res = await ex.execute(info_tool, {}, context=_ctx(PermissionProfile.STANDARD))
    assert res.success is True
    assert res.result == "ran"


# =============================================================================
# Phase 2.4 — Request-scoped, owner-aware confirmation callbacks
# =============================================================================


class _RecordingCallback:
    def __init__(self, decision=True):
        self.decision = decision
        self.calls = 0

    async def request_approval(self, tool_name, args, request_id, preview=""):
        self.calls += 1
        return self.decision


@pytest.mark.asyncio
async def test_scoped_confirmation_callbacks_are_isolated():
    from src.infra.tools.base import ToolExecutor

    ex = ToolExecutor()
    cb_a = _RecordingCallback(decision=True)
    cb_b = _RecordingCallback(decision=False)
    ex.register_confirmation_callback("sess-a", cb_a)
    ex.register_confirmation_callback("sess-b", cb_b)

    # Each session resolves its own callback — no cross-talk.
    assert ex._resolve_confirmation_callback(None, "sess-a") is cb_a
    assert ex._resolve_confirmation_callback(None, "sess-b") is cb_b
    # Explicit override wins.
    override = _RecordingCallback()
    assert ex._resolve_confirmation_callback(override, "sess-a") is override
    # Unknown session → global default (None here).
    assert ex._resolve_confirmation_callback(None, "sess-x") is None

    ex.unregister_confirmation_callback("sess-a")
    assert ex._resolve_confirmation_callback(None, "sess-a") is None


@pytest.mark.asyncio
async def test_confirmation_uses_session_scoped_callback():
    """A risky tool uses the callback registered for the executing session."""
    from src.infra.tools.base import ToolExecutor

    ex = ToolExecutor()
    approver = _RecordingCallback(decision=True)
    ex.register_confirmation_callback("owner-session", approver)

    risky = _make_tool("risky_fs", "FILE_SYSTEM", requires_confirmation=True)  # min system_full
    res = await ex.execute(
        risky, {}, context=_ctx(PermissionProfile.SYSTEM_FULL, session_id="owner-session")
    )
    assert approver.calls == 1
    assert res.success is True
