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
        None,
        {"a": 1},
    ],
)
def test_results_are_not_flagged(output):
    assert not reported_failure(output)
