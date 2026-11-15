"""Tool outputs that are failure messages must not count as successes."""

from __future__ import annotations

import pytest

from src.infra.tools.base import ToolFailure, reported_failure


@pytest.mark.parametrize(
    "output",
    [
        "🚫 Access denied — path is outside the agent workspace.",
        "❌ 'docs' is not a directory.",
        "copy_file source - Access denied: x is outside the allowed directories",
        "Error: No coin provided.",
        "Code execution unavailable: disabled",
        "Screenshot failed. Install Pillow",
        "Memory service is not enabled.",
        "GPU monitoring requires GPUtil. Install with: pip install gputil",
        "Cannot find 'xyzzy' on this system. You may need to scan.",
        "Could not launch 'slack': permission denied",
        "Failed to open spotify: boom",
        "Unable to reach the server",
        "Source file does not exist: /tmp/a.txt",
        "File not found: notes.txt",
        "No such file or directory",
        ToolFailure("nope"),
    ],
)
def test_failure_messages_are_detected(output):
    assert reported_failure(output)


@pytest.mark.parametrize(
    "output",
    [
        "17 * 23 = 391",
        "📄 **notes.txt**: Error handling notes",
        "🌐 **Content from** x: Error 404 explained",
        "No tasks found.",
        "Command succeeded: Error: none",
        "Errors are common in code",
        "Opening firefox...",
        "File copied to /tmp/b.txt",
        "Found 2 relevant file snippet(s) for: 'x'",
        "The file was found in 3 places",
        None,
        {"a": 1},
    ],
)
def test_results_are_not_flagged(output):
    assert not reported_failure(output)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("given", "expected"), [("py", "*.py"), (".md", "*.md"), ("*.py", "*.py"), ("", "*")]
)
async def test_search_codebase_normalises_file_pattern(monkeypatch, given, expected):
    import asyncio

    from src.infra.tools import agent_tools

    seen: list[str] = []

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"/x/src/a.py\n", b""

    async def fake_exec(*args, **_):
        seen.extend(a for a in args if str(a).startswith("--include="))
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    tool = next(t for t in agent_tools.build_agent_tools() if t.name == "search_codebase")
    await tool.function(query="IntentRouter", file_pattern=given)
    assert seen == [f"--include={expected}"]
