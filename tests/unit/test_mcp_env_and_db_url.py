"""MCP server env passthrough and async database URL normalisation."""

from __future__ import annotations

import pytest

from src.app.services.tool_registry import resolve_mcp_env


def test_mcp_env_expands_references(monkeypatch):
    monkeypatch.setenv("GH_TOKEN_TEST", "secret-value")
    env = resolve_mcp_env({"GITHUB_TOKEN": "${GH_TOKEN_TEST}", "MODE": "ro"}, "github")
    assert env == {"GITHUB_TOKEN": "secret-value", "MODE": "ro"}


def test_mcp_env_drops_unset_references(monkeypatch, caplog):
    monkeypatch.delenv("NOPE_NOT_SET", raising=False)
    env = resolve_mcp_env({"TOKEN": "${NOPE_NOT_SET}", "KEEP": "x"}, "srv")
    assert env == {"KEEP": "x"}  # never a literal "${...}" or empty credential
    assert "NOPE_NOT_SET" in caplog.text


@pytest.mark.parametrize("env", [None, {}])
def test_mcp_env_empty_means_sdk_default(env):
    assert resolve_mcp_env(env) is None


@pytest.mark.asyncio
async def test_connect_passes_env_to_server_params(monkeypatch):
    import mcp

    from src.app.services.tool_registry import ToolRegistry

    seen = {}

    class _Params:
        def __init__(self, command, args, env=None):
            seen.update(command=command, args=args, env=env)
            raise RuntimeError("stop before spawning")

    monkeypatch.setattr(mcp, "StdioServerParameters", _Params)
    monkeypatch.setenv("MCP_TEST_TOKEN", "t0k")
    count = await ToolRegistry().connect_mcp_server(
        "npx -y some-server --flag", "test", env={"TOKEN": "${MCP_TEST_TOKEN}"}
    )
    assert count == 0
    assert seen == {
        "command": "npx",
        "args": ["-y", "some-server", "--flag"],
        "env": {"TOKEN": "t0k"},
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///./data/a.db", "sqlite+aiosqlite:///./data/a.db"),
        ("sqlite+aiosqlite:///./data/a.db", "sqlite+aiosqlite:///./data/a.db"),
        ("sqlite+aiosqlite:////tmp/x.y/a.db", "sqlite+aiosqlite:////tmp/x.y/a.db"),
    ],
)
def test_async_sqlite_url_is_idempotent(monkeypatch, url, expected):
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    assert settings.get_async_database_url() == expected
