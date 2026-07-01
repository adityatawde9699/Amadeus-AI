"""
Security regression tests for remediation Phase 3 & 4.

Covers:
  * SSRF egress guard (assert_public_url / fetch_webpage_content)
  * manage_plugins: admin-only capability + path containment + no same-request import
  * filesystem _safe_resolve real containment (no string-prefix bypass)
  * auth manager no longer logs reset/verify tokens
  * per-IP pre-auth rate limiting middleware
  * docker-compose: datastores publish no public ports
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infra.tools.net_guard import UrlNotAllowedError, assert_public_url


# =============================================================================
# Phase 3.1 — SSRF egress guard
# =============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "https://0.0.0.0/",
    ],
)
def test_assert_public_url_blocks_internal(url):
    with pytest.raises(UrlNotAllowedError):
        assert_public_url(url)


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://x"])
def test_assert_public_url_blocks_bad_scheme(url):
    with pytest.raises(UrlNotAllowedError):
        assert_public_url(url)


def test_assert_public_url_allows_public_ip_literal():
    # 8.8.8.8 is globally routable; no DNS needed for an IP literal.
    assert assert_public_url("https://8.8.8.8/") == "https://8.8.8.8/"


def test_assert_public_url_allow_private_escape_hatch():
    # Dev-only bypass must still work when explicitly enabled.
    assert assert_public_url("http://127.0.0.1/", allow_private=True)


@pytest.mark.asyncio
async def test_fetch_webpage_content_refuses_internal(monkeypatch):
    import src.core.config as cfg
    from src.core.config import Settings
    from src.infra.tools.web_research_tools import build_web_research_tools

    monkeypatch.setattr(
        cfg,
        "get_settings",
        lambda: Settings(ALLOW_PRIVATE_NETWORK_FETCH=False, SKIP_CONFIG_VALIDATION=True),
    )

    tools = build_web_research_tools()
    fetch = next(t for t in tools if t.name == "fetch_webpage_content")
    out = await fetch.function(url="http://169.254.169.254/latest/meta-data/")
    assert "refused" in out.lower()


# =============================================================================
# Phase 3.2 — manage_plugins hardening
# =============================================================================


def _get_manage_plugins_tool():
    from src.infra.tools.agent_tools import build_agent_tools

    tools = build_agent_tools()
    return next(t for t in tools if t.name == "manage_plugins")


def test_manage_plugins_requires_system_full():
    tool = _get_manage_plugins_tool()
    assert tool.capability is not None
    assert tool.capability.min_permission == "system_full"
    assert tool.capability.requires_confirmation is True


@pytest.mark.asyncio
async def test_manage_plugins_blocks_path_traversal(monkeypatch, tmp_path):
    import src.infra.tools.agent_tools as at
    from src.core.config import Settings

    monkeypatch.setattr(
        at, "get_settings", lambda: Settings(BASE_DIR=tmp_path, SKIP_CONFIG_VALIDATION=True)
    )
    tool = _get_manage_plugins_tool()

    out = await tool.function(action="add", plugin_name="../../evil.py", content="x = 1")
    assert "denied" in out.lower()
    # Nothing must have been written outside the plugins dir.
    assert not (tmp_path.parent / "evil.py").exists()


@pytest.mark.asyncio
async def test_manage_plugins_add_does_not_import(monkeypatch, tmp_path):
    """A successful add writes the file but must NOT load it in the same request."""
    import src.infra.tools.agent_tools as at
    from src.core.config import Settings

    monkeypatch.setattr(
        at, "get_settings", lambda: Settings(BASE_DIR=tmp_path, SKIP_CONFIG_VALIDATION=True)
    )
    tool = _get_manage_plugins_tool()

    out = await tool.function(action="add", plugin_name="good.py", content="X = 1")
    assert "restart" in out.lower()
    assert (tmp_path / "plugins" / "good.py").exists()


# =============================================================================
# Phase 3.3 — filesystem containment (no string-prefix bypass)
# =============================================================================


def test_safe_resolve_blocks_traversal(monkeypatch, tmp_path):
    import src.infra.tools.filesystem_tools as fst

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(fst, "_get_workspace", lambda: workspace)

    assert fst._safe_resolve("../../etc/passwd") is None
    assert fst._safe_resolve("/etc/passwd") is None


def test_safe_resolve_no_sibling_prefix_bypass(monkeypatch, tmp_path):
    """'/ws' must not accept a sibling '/ws-evil' (the old startswith bug)."""
    import src.infra.tools.filesystem_tools as fst

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "ws-evil").mkdir()
    monkeypatch.setattr(fst, "_get_workspace", lambda: workspace)

    # Relative traversal into the sibling resolves outside the workspace.
    assert fst._safe_resolve("../ws-evil/secret.txt") is None
    # A legit in-workspace path still resolves.
    assert fst._safe_resolve("notes.txt") == (workspace.resolve() / "notes.txt")


# =============================================================================
# Phase 4.1 — no token logging
# =============================================================================


@pytest.mark.asyncio
async def test_forgot_password_does_not_log_token(monkeypatch, caplog):
    import logging

    import src.api.auth.manager as mgr
    from src.core.config import Settings

    monkeypatch.setattr(
        mgr, "get_settings", lambda: Settings(ENV="production", SKIP_CONFIG_VALIDATION=True)
    )

    manager = mgr.UserManager.__new__(mgr.UserManager)
    user = type("U", (), {"id": 7})()

    with caplog.at_level(logging.DEBUG):
        await manager.on_after_forgot_password(user, token="SUPERSECRET-TOKEN")

    assert "SUPERSECRET-TOKEN" not in caplog.text


# =============================================================================
# Phase 4.3 — per-IP pre-auth rate limiting
# =============================================================================


def test_rate_limit_middleware_throttles(monkeypatch):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import src.api.middleware.rate_limit as rl
    from src.core.config import Settings

    monkeypatch.setattr(
        rl,
        "get_settings",
        lambda: Settings(
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_AUTH_REQUESTS=3,
            RATE_LIMIT_AUTH_WINDOW_SECONDS=60,
            SKIP_CONFIG_VALIDATION=True,
        ),
    )

    async def login(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/v1/auth/jwt/login", login, methods=["POST"])])
    app.add_middleware(rl.RateLimitMiddleware)
    client = TestClient(app)

    codes = [client.post("/api/v1/auth/jwt/login").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429


def test_rate_limit_ignores_non_auth_paths(monkeypatch):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import src.api.middleware.rate_limit as rl
    from src.core.config import Settings

    monkeypatch.setattr(
        rl,
        "get_settings",
        lambda: Settings(
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_AUTH_REQUESTS=1,
            RATE_LIMIT_AUTH_WINDOW_SECONDS=60,
            SKIP_CONFIG_VALIDATION=True,
        ),
    )

    async def chat(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/v1/chat", chat, methods=["POST"])])
    app.add_middleware(rl.RateLimitMiddleware)
    client = TestClient(app)

    codes = [client.post("/api/v1/chat").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 200]


# =============================================================================
# Phase 4.4 — docker-compose: datastores expose no public ports
# =============================================================================


def test_compose_datastores_have_no_public_ports():
    import re

    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()

    # No service may publish on the wildcard interface "host:container" without a
    # loopback bind. Every ports entry present must be 127.0.0.1-bound.
    port_lines = re.findall(r'-\s*"([^"]+)"', compose)
    publish_lines = [p for p in port_lines if ":" in p and "/" not in p]
    for entry in publish_lines:
        assert entry.startswith("127.0.0.1:"), f"Non-loopback port publish: {entry}"
