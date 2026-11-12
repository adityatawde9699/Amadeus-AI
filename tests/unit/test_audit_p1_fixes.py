"""
Regression tests for the 2026-11 audit P1 fixes.

- H-5:  proactive checks run the agent READ_ONLY and deliver results in code.
- H-3b: factory-built ``Tool(...)`` objects always carry a capability.
- M-2:  calculator rejects resource-exhaustion expressions.
- M-5:  ping / grep argument-injection guards.
- P1-5: llama.cpp inference is serialised.
- P1-7: argument-remap heuristic only applies to read-only tools.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile


if TYPE_CHECKING:
    from pathlib import Path


def _ctx(profile: PermissionProfile) -> RequestContext:
    return RequestContext(request_id="r", session_id="s", user_id="u", permissions=profile)


# =============================================================================
# H-3b: every Tool has a capability; factory read tools stay READ_ONLY-usable
# =============================================================================


def _task_tools():
    from src.infra.tools.productivity_tools import build_task_tools

    repo = MagicMock()
    repo.get_all = AsyncMock(return_value=[])
    repo.get_summary = AsyncMock(return_value={"total": 0, "pending": 0, "completed": 0})
    repo.create = AsyncMock()
    return {t.name: t for t in build_task_tools(repo)}, repo


def test_direct_tool_construction_derives_capability():
    from src.infra.tools.base import Tool, ToolCategory

    t = Tool(name="x", function=lambda: 1, description="d", category=ToolCategory.DEVELOPER)
    assert t.capability is not None
    assert t.capability.min_permission == "system_full"
    assert t.capability.explicit is False


@pytest.mark.asyncio
async def test_read_only_session_can_read_but_not_mutate_tasks():
    from src.infra.tools.base import ToolExecutor

    tools, repo = _task_tools()
    ex = ToolExecutor()
    ro = _ctx(PermissionProfile.READ_ONLY)

    assert (await ex.execute(tools["list_tasks"], {}, context=ro)).success is True
    assert (await ex.execute(tools["get_task_summary"], {}, context=ro)).success is True

    denied = await ex.execute(tools["add_task"], {"task_content": "x"}, context=ro)
    assert denied.success is False
    assert "security policy" in (denied.error_message or "").lower()
    repo.create.assert_not_called()


# =============================================================================
# H-5: proactive checks
# =============================================================================


def _patch_proactive(response: str | None):
    service = MagicMock()
    service.memory_service = None
    service.handle_background_event = AsyncMock(return_value=response)
    messaging = MagicMock()
    messaging.send_message = AsyncMock(return_value=True)
    settings = SimpleNamespace(MASTER_TELEGRAM_CHAT_ID="12345")
    container = SimpleNamespace(amadeus_service=lambda: service)
    return service, messaging, [
        patch("src.app.services.proactive_service.get_settings", return_value=settings),
        patch("src.container.global_container", container),
        patch("src.container.get_messaging_service", return_value=messaging),
    ]


@pytest.mark.asyncio
async def test_proactive_check_runs_read_only_and_delivers_in_code():
    from src.app.services.proactive_service import run_proactive_checks

    service, messaging, patches = _patch_proactive("Task 'pay rent' is overdue.")
    for p in patches:
        p.start()
    try:
        await run_proactive_checks()
    finally:
        for p in patches:
            p.stop()

    ctx = service.handle_background_event.await_args.kwargs["context"]
    assert ctx.permissions == PermissionProfile.READ_ONLY
    messaging.send_message.assert_awaited_once()
    kwargs = messaging.send_message.await_args.kwargs
    assert kwargs["recipient_id"] == "12345"
    assert kwargs["platform"] == "telegram"
    assert "pay rent" in kwargs["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["NO_ACTION", "  no_action.  ", "", None])
async def test_proactive_check_stays_silent_when_nothing_to_report(response):
    from src.app.services.proactive_service import run_proactive_checks

    _, messaging, patches = _patch_proactive(response)
    for p in patches:
        p.start()
    try:
        await run_proactive_checks()
    finally:
        for p in patches:
            p.stop()
    messaging.send_message.assert_not_called()


# =============================================================================
# M-2: calculator
# =============================================================================


def _calc(expr: str) -> str:
    from src.infra.tools.info_tools import calculate

    return calculate(expr)


@pytest.mark.parametrize(
    "expr",
    ["pow(10, 10**1000)", "((10**1000)**1000)**1000", "10.0**400", "2**5000"],
)
def test_calculator_rejects_resource_exhaustion(expr):
    start = time.monotonic()
    out = _calc(expr)
    assert time.monotonic() - start < 1.0
    assert "=" not in out


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("2+2", "4"), ("2**10", "1024"), ("sqrt(144)", "12.0"), ("3 × 4", "12"), ("-2**3", "-8")],
)
def test_calculator_still_handles_normal_math(expr, expected):
    assert _calc(expr).endswith(f"= {expected}")


# =============================================================================
# M-5: argument-injection guards
# =============================================================================


@pytest.mark.parametrize("host", ["-f", "--flood", "a b", "x;rm -rf /", ""])
def test_ping_rejects_option_like_or_invalid_hosts(host):
    from src.infra.tools.network_tools import ping_host

    with patch("src.infra.tools.network_tools.subprocess.run") as run:
        out = ping_host(host)
    run.assert_not_called()
    assert out.startswith("Error: invalid host")


def test_ping_clamps_count_and_passes_valid_host():
    from src.infra.tools.network_tools import ping_host

    with patch("src.infra.tools.network_tools.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        ping_host("example.com", count=10_000)
    cmd = run.call_args.args[0]
    assert cmd[-1] == "example.com"
    assert cmd[2] == "10"


@pytest.mark.asyncio
async def test_search_codebase_ends_option_parsing():
    from src.infra.tools.agent_tools import build_agent_tools

    tool = next(t for t in build_agent_tools() if t.name == "search_codebase")
    proc = MagicMock(returncode=1)
    proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)
    ) as spawn:
        await tool.function(query="-f /etc/passwd")
    args = spawn.await_args.args
    assert args[args.index("--") + 1] == "-f /etc/passwd"


# =============================================================================
# P1-7: argument remap only for read-only tools
# =============================================================================


def _tool(name, fn, category, requires_confirmation=False):
    from src.infra.tools.base import Tool

    return Tool(
        name=name,
        function=fn,
        description="d",
        category=category,
        requires_confirmation=requires_confirmation,
    )


def test_remap_applies_to_read_only_tool():
    from src.infra.tools.base import ToolCategory, ToolExecutor

    def calc(expression: str) -> str:
        return expression

    cleaned = ToolExecutor()._validate_args(
        _tool("calc", calc, ToolCategory.CALCULATION), {"expr": "2+2"}
    )
    assert cleaned.get("expression") == "2+2"


def test_remap_refused_for_mutating_tool():
    from src.infra.tools.base import ToolCategory, ToolExecutor

    def delete_file(path: str) -> str:
        return path

    cleaned = ToolExecutor()._validate_args(
        _tool("delete_file", delete_file, ToolCategory.FILE_SYSTEM), {"target": "/etc"}
    )
    assert "path" not in cleaned
    assert "_validation_error" in cleaned


# =============================================================================
# P1-5: llama.cpp inference serialisation
# =============================================================================


@pytest.mark.asyncio
async def test_llama_inference_is_serialised(tmp_path: Path):
    from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter

    model = tmp_path / "m.gguf"
    model.write_bytes(b"\x00" * 64)
    adapter = LlamaCppAdapter(model_path=str(model), threads=1, context_length=64)

    active = 0
    peak = 0
    guard = threading.Lock()

    def fake_completion(**kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return {"choices": [{"message": {"content": "ok"}}]}

    llm = MagicMock()
    llm.create_chat_completion.side_effect = fake_completion
    with patch.object(LlamaCppAdapter, "_get_llm", new=AsyncMock(return_value=llm)):
        results = await asyncio.gather(*(adapter.generate_response("hi") for _ in range(4)))

    assert results == ["ok"] * 4
    assert peak == 1
