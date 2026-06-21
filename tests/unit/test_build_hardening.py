"""
Build / deployment hardening regression tests.

Guards the fixes from the build audit so they cannot silently regress:
  * runtime daemon must not import torch / sklearn (CLAUDE.md §3 memory budget)
  * SSRF guard resolves DNS off the event loop, with a fail-closed timeout
  * rate-limit middleware bounds memory (evicts stale IP buckets) + window reset
  * Docker build is reproducible (uses the lockfile, no torch extra)
  * /chat/clear requires authentication (no anonymous global wipe)
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import time
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# Memory budget — no torch/sklearn in the runtime import graph (CLAUDE.md §3)
# =============================================================================


@pytest.mark.parametrize(
    "module",
    [
        "src.app.services.semantic_router",
        "src.app.services.category_classifier",
        "src.infra.tools.web_research_tools",
    ],
)
def test_runtime_modules_do_not_import_torch_or_sklearn(module):
    """Importing core routing modules must not drag in the heavy ML stack.

    Run in a clean subprocess so another test having imported torch can't mask a
    regression. torch/sklearn live behind lazy imports + the [ml-fallback] extra.
    """
    code = (
        "import sys, importlib;"
        f"importlib.import_module('{module}');"
        "bad=[m for m in ('torch','sklearn','transformers','scipy') if m in sys.modules];"
        "assert not bad, f'heavy ML stack imported at runtime: {bad}'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=_ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


# =============================================================================
# SSRF guard — non-blocking DNS with fail-closed timeout
# =============================================================================


@pytest.mark.asyncio
async def test_assert_public_url_async_allows_public_literal():
    from src.infra.tools.net_guard import assert_public_url_async

    assert await assert_public_url_async("https://8.8.8.8/") == "https://8.8.8.8/"


@pytest.mark.asyncio
async def test_assert_public_url_async_blocks_internal():
    from src.infra.tools.net_guard import UrlNotAllowedError, assert_public_url_async

    with pytest.raises(UrlNotAllowedError):
        await assert_public_url_async("http://127.0.0.1/")


@pytest.mark.asyncio
async def test_dns_resolution_times_out_fail_closed(monkeypatch):
    """A hanging resolver must fail closed quickly, not stall the event loop."""
    import src.infra.tools.net_guard as ng

    def _slow_resolve(host):
        time.sleep(2.0)  # simulate a hostile/slow resolver (runs in a thread)
        return []

    monkeypatch.setattr(ng, "_resolve_addresses", _slow_resolve)

    start = time.monotonic()
    with pytest.raises(ng.UrlNotAllowedError, match="timed out"):
        await ng.assert_public_url_async("http://slow.example.com/", dns_timeout=0.2)
    elapsed = time.monotonic() - start
    # Must return on the timeout (~0.2s), well before the 2s blocking sleep.
    assert elapsed < 1.5


@pytest.mark.asyncio
async def test_dns_resolution_runs_off_event_loop(monkeypatch):
    """Resolution must go through asyncio.to_thread (keeps the loop responsive)."""
    import src.infra.tools.net_guard as ng

    main_thread = __import__("threading").get_ident()
    seen: dict[str, int] = {}

    def _record_resolve(host):
        seen["thread"] = __import__("threading").get_ident()
        import ipaddress

        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(ng, "_resolve_addresses", _record_resolve)
    await ng.assert_public_url_async("http://example.com/")
    assert seen["thread"] != main_thread, "DNS resolved on the event-loop thread"


# =============================================================================
# Rate-limit middleware — memory bound + window reset
# =============================================================================


def _make_middleware():
    from src.api.middleware.rate_limit import RateLimitMiddleware

    async def _app(scope, receive, send):  # minimal ASGI app
        return None

    return RateLimitMiddleware(_app)


def test_rate_limit_sweep_evicts_stale_ips():
    from collections import deque

    mw = _make_middleware()
    now = 1000.0
    window = 60.0
    # Three IPs: two stale (last hit outside window), one fresh.
    mw._hits["stale-1"] = deque([now - 120])
    mw._hits["stale-2"] = deque([now - 61])
    mw._hits["fresh"] = deque([now - 5])

    mw._sweep(now, window)

    assert set(mw._hits.keys()) == {"fresh"}


def test_rate_limit_window_reset_and_no_unbounded_growth(monkeypatch):
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
    # Controllable clock so we can advance past the window deterministically.
    clock = {"t": 1000.0}
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock["t"])

    async def login(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/v1/auth/jwt/login", login, methods=["POST"])])
    app.add_middleware(rl.RateLimitMiddleware)
    client = TestClient(app)

    # Exhaust the window.
    assert [client.post("/api/v1/auth/jwt/login").status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]
    # Advance past the window — the limit resets AND the stale bucket is swept.
    clock["t"] += 61
    assert client.post("/api/v1/auth/jwt/login").status_code == 200


# =============================================================================
# Reproducible build — Dockerfile uses the lockfile, not torch
# =============================================================================


def test_dockerfile_is_reproducible_and_lite():
    dockerfile = (_ROOT / "Dockerfile").read_text()
    # Must install from the frozen lockfile, never re-resolve ranges.
    assert "uv sync --frozen" in dockerfile
    assert "pip install --no-cache-dir ." not in dockerfile
    # No install directive may pull the heavy ML extra into the runtime image
    # (comments mentioning it are fine — check the actual uv sync RUN lines).
    install_lines = [
        ln for ln in dockerfile.splitlines() if "uv sync" in ln and not ln.lstrip().startswith("#")
    ]
    assert install_lines, "expected at least one `uv sync` install line"
    for ln in install_lines:
        assert "ml-fallback" not in ln and "--all-extras" not in ln


def test_dockerignore_excludes_env_files():
    ignore = (_ROOT / ".dockerignore").read_text()
    assert ".env" in ignore
    assert "!.env.example" in ignore


# =============================================================================
# Regression — /chat/clear requires authentication
# =============================================================================


def test_clear_conversation_requires_authenticated_user():
    from src.api.auth.manager import current_active_user
    from src.api.routes.chat import clear_conversation

    sig = inspect.signature(clear_conversation)
    user_param = sig.parameters.get("user")
    assert user_param is not None, "clear_conversation must take an authenticated user"
    # The default is a FastAPI Depends() wrapping current_active_user.
    dep = user_param.default
    assert getattr(dep, "dependency", None) is current_active_user
