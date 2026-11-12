"""
Regression tests for the 2026-11 audit P0 fixes.

- H-1/H-2: HITL confirmations are bound to the requesting session and the REST
  routes authenticate with the fastapi-users backend + enforce ownership.
- H-3:     tools registered via ``register_function`` (incl. MCP) always carry a
  capability, so the policy engine can no longer be bypassed.
- M-1:     the ephemeral SECRET_KEY is generated once per process.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile


def _ctx(profile: PermissionProfile, session_id: str = "s1") -> RequestContext:
    return RequestContext(
        request_id="r1", session_id=session_id, user_id=session_id, permissions=profile
    )


# =============================================================================
# H-3: register_function / MCP capability enforcement
# =============================================================================


class _FakeMCPTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"fake {name}"
        self.inputSchema = {}


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, name, kwargs):
        self.calls.append(name)
        return SimpleNamespace(content=[SimpleNamespace(text=f"ran {name}")])


def test_register_function_derives_capability():
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.tools.base import ToolCategory

    reg = ToolRegistry()
    reg.register_function(lambda: "x", "dev_fn", "d", ToolCategory.DEVELOPER)
    tool = reg.get("dev_fn")
    assert tool is not None
    assert tool.capability is not None
    assert tool.capability.min_permission == "system_full"
    assert tool.capability.explicit is False


@pytest.mark.asyncio
async def test_mcp_tool_denied_for_read_only_and_gated_for_standard():
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.tools.base import ToolExecutor

    reg = ToolRegistry()
    session = _FakeSession()
    reg._register_mcp_tool(session, _FakeMCPTool("write_file"), server_name="filesystem")
    tool = reg.get("filesystem_write_file")
    assert tool is not None and tool.requires_confirmation

    ex = ToolExecutor()  # no confirmation callback → confirmation-gated tools denied
    denied = await ex.execute(tool, {}, context=_ctx(PermissionProfile.READ_ONLY))
    assert denied.success is False
    assert "security policy" in (denied.error_message or "").lower()

    no_cb = await ex.execute(tool, {}, context=_ctx(PermissionProfile.STANDARD))
    assert no_cb.success is False
    assert "confirmation" in (no_cb.error_message or "").lower()
    assert session.calls == []


@pytest.mark.asyncio
async def test_mcp_read_only_tool_runs_without_confirmation():
    from src.app.services.tool_registry import ToolRegistry
    from src.infra.tools.base import ToolExecutor

    reg = ToolRegistry()
    session = _FakeSession()
    reg._register_mcp_tool(
        session, _FakeMCPTool("read_file"), server_name="filesystem", read_only=True
    )
    tool = reg.get("filesystem_read_file")
    assert tool is not None and not tool.requires_confirmation

    res = await ToolExecutor().execute(tool, {}, context=_ctx(PermissionProfile.READ_ONLY))
    assert res.success is True
    assert session.calls == ["read_file"]


def test_mcp_tool_needs_hitl_in_agent_graph():
    from src.app.services.agent_loop import AmadeusGraph
    from src.app.services.tool_registry import ToolRegistry

    reg = ToolRegistry()
    reg._register_mcp_tool(_FakeSession(), _FakeMCPTool("move_file"), server_name="fs")
    assert AmadeusGraph._needs_approval(reg.get("fs_move_file")) is True


# =============================================================================
# H-2: confirmation ownership binding
# =============================================================================


def _confirm_tool():
    from src.infra.tools.base import Tool, ToolCategory

    return Tool(
        name="danger",
        function=lambda **kw: "done",
        description="d",
        category=ToolCategory.TASK_MANAGER,
        parameters={},
        requires_confirmation=True,
    )


@pytest.mark.asyncio
async def test_api_confirmation_is_bound_to_requesting_session():
    from src.infra.tools.base import ToolExecutor
    from src.infra.tools.confirmation import APIConfirmationCallback

    cb = APIConfirmationCallback(timeout_seconds=5)
    ex = ToolExecutor(confirmation_callback=cb)
    task = asyncio.create_task(
        ex.execute(_confirm_tool(), {}, context=_ctx(PermissionProfile.SYSTEM_FULL, "42"))
    )
    for _ in range(50):
        if cb._pending:
            break
        await asyncio.sleep(0.01)

    (pending,) = cb._pending.values()
    assert pending.session_id == "42"
    assert cb.is_owner(pending, "42")
    assert not cb.is_owner(pending, "43")
    assert cb.list_pending("43") == []
    assert len(cb.list_pending("42")) == 1

    cb.approve(pending.request_id, True)
    res = await task
    assert res.success is True


def test_unowned_confirmation_matches_nobody():
    from src.infra.tools.confirmation import APIConfirmationCallback, PendingConfirmation

    async def _run():
        p = PendingConfirmation(request_id="x", tool_name="t", args={})
        assert APIConfirmationCallback.is_owner(p, None) is False
        assert APIConfirmationCallback.is_owner(p, "1") is False

    asyncio.run(_run())


# =============================================================================
# H-1/H-2: /confirm routes — fastapi-users auth + ownership
# =============================================================================


def _confirm_client(user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.middleware.rbac import RequireUser
    from src.api.routes import confirm
    from src.infra.tools.confirmation import APIConfirmationCallback, PendingConfirmation

    app = FastAPI()
    app.include_router(confirm.router, prefix="/api/v1")
    cb = APIConfirmationCallback()
    app.state.confirmation_callback = cb
    app.dependency_overrides[RequireUser] = lambda: user

    class _Future:
        def __init__(self):
            self.value = None

        def done(self):
            return self.value is not None

        def set_result(self, v):
            self.value = v

    cb._pending["req-a"] = PendingConfirmation(
        request_id="req-a", tool_name="t", args={"k": 1}, session_id="1", future=_Future()
    )
    return TestClient(app), cb


def _user(uid: int, role: str):
    from src.infra.persistence.orm_models import UserRoleDB

    return SimpleNamespace(id=uid, role=UserRoleDB(role))


def test_owner_can_resolve_own_confirmation():
    client, cb = _confirm_client(_user(1, "user"))
    assert client.get("/api/v1/confirm/req-a").status_code == 200
    r = client.post("/api/v1/confirm/req-a", json={"approved": True})
    assert r.status_code == 200
    assert cb._pending["req-a"].future.value is True


def test_other_user_cannot_see_or_resolve_confirmation():
    client, cb = _confirm_client(_user(2, "user"))
    assert client.get("/api/v1/confirm/req-a").status_code == 404
    assert client.post("/api/v1/confirm/req-a", json={"approved": True}).status_code == 404
    assert client.get("/api/v1/confirm").json() == {"pending": []}
    assert cb._pending["req-a"].future.value is None


def test_admin_sees_all_confirmations():
    client, _ = _confirm_client(_user(9, "admin"))
    assert len(client.get("/api/v1/confirm").json()["pending"]) == 1
    assert client.post("/api/v1/confirm/req-a", json={"approved": False}).status_code == 200


def test_confirm_and_messaging_use_fastapi_users_auth():
    """The legacy python-jose verifier (rejected login tokens) must be gone."""
    from src.transports.fastapi_transport import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(("/api/v1/confirm", "/api/v1/messaging")):
            names = {
                getattr(d.call, "__name__", type(d.call).__name__)
                for d in route.dependant.dependencies
            }
            assert "verify_jwt_token" not in names, path
            assert "RequireRole" in names, path


# =============================================================================
# M-1: ephemeral SECRET_KEY stability
# =============================================================================


def test_ephemeral_secret_key_is_stable(monkeypatch):
    from src.core import config

    monkeypatch.setattr(config, "_EPHEMERAL_SECRET_KEY", None)
    settings = SimpleNamespace(SECRET_KEY="")
    first = config._get_or_create_secret_key(settings)
    assert first
    assert config._get_or_create_secret_key(settings) == first

    assert config._get_or_create_secret_key(SimpleNamespace(SECRET_KEY="fixed")) == "fixed"
