from __future__ import annotations

import pytest

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile
from src.infra.tools.base import Tool, ToolCapability, ToolCategory
from src.infra.tools.policy import ToolPolicyEngine, ToolPolicyViolation


def _tool(capability: ToolCapability) -> Tool:
    def noop(**kwargs):
        return "ok"

    return Tool(
        name=capability.name,
        function=noop,
        description="test tool",
        category=ToolCategory.SYSTEM,
        capability=capability,
    )


def _context(permission: PermissionProfile) -> RequestContext:
    return RequestContext(
        request_id="req-policy",
        session_id="session-policy",
        user_id="user-policy",
        permissions=permission,
    )


def test_read_only_blocks_mutating_tool():
    policy = ToolPolicyEngine()
    tool = _tool(ToolCapability(name="write_file", modifies_filesystem=True))

    with pytest.raises(ToolPolicyViolation):
        policy.evaluate(tool, {}, _context(PermissionProfile.READ_ONLY))


def test_critical_tool_must_require_confirmation():
    policy = ToolPolicyEngine()
    tool = _tool(ToolCapability(name="format_disk", risk_level="critical"))

    with pytest.raises(ToolPolicyViolation):
        policy.evaluate(tool, {}, _context(PermissionProfile.SYSTEM_FULL))


def test_terminal_command_blocks_forbidden_tokens():
    policy = ToolPolicyEngine()
    tool = _tool(
        ToolCapability(
            name="terminal_cmd",
            risk_level="high",
            requires_confirmation=True,
        )
    )

    with pytest.raises(ToolPolicyViolation):
        policy.evaluate(
            tool,
            {"command": "rm -rf /"},
            _context(PermissionProfile.SYSTEM_FULL),
        )
