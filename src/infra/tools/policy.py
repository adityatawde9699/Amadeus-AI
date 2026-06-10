"""
Tool Policy Engine for Amadeus AI.

Enforces security boundaries, permissions, and risk management
before any tool is executed by the ToolExecutor.
"""

import logging
from typing import TYPE_CHECKING, Any

from src.core.domain.context import RequestContext
from src.core.domain.models import PermissionProfile


if TYPE_CHECKING:
    from src.infra.tools.base import Tool

logger = logging.getLogger(__name__)

class ToolPolicyViolation(Exception):
    """Raised when a tool execution request violates security policy."""

class ToolPolicyEngine:
    """
    Evaluates execution requests against established security policies.
    """

    def __init__(self, is_development_mode: bool = False):
        self.is_development_mode = is_development_mode

    def evaluate(self, tool: "Tool", args: dict[str, Any], context: RequestContext) -> None:
        """
        Evaluate if the tool can be safely executed in the given context.
        Raises ToolPolicyViolation if the execution is unsafe.
        """
        capability = tool.capability

        # If no explicit capability is defined, we enforce basic safety checks
        # based on the tool's defined `requires_confirmation` flag.
        if not capability:
            if context.permissions == PermissionProfile.READ_ONLY and tool.requires_confirmation:
                raise ToolPolicyViolation(
                    f"Tool {tool.name} requires confirmation but session is READ_ONLY."
                )
            return

        # 1. Permission Profile Checks
        if context.permissions == PermissionProfile.READ_ONLY:
            if capability.modifies_filesystem or capability.modifies_system_state:
                raise ToolPolicyViolation(
                    f"READ_ONLY session cannot execute mutating tool: {tool.name}"
                )
            if capability.risk_level in ("high", "critical"):
                raise ToolPolicyViolation(
                    f"READ_ONLY session cannot execute high-risk tool: {tool.name}"
                )

        # 2. Risk & Confirmation Checks
        # The executor handles the actual confirmation flow, but the policy engine
        # ensures that critical tools are never executed implicitly without the flag set.
        if (
            capability.risk_level == "critical"
            and not capability.requires_confirmation
            and not self.is_development_mode
        ):
            raise ToolPolicyViolation(
                f"Critical tool {tool.name} must declare requires_confirmation=True"
            )

        # 3. Sandbox Checks
        # Currently, if a tool says it requires a sandbox, we verify it is categorized correctly.
        if getattr(capability, "sandbox_required", False) and "execute_python" not in tool.name:
            logger.warning("Tool %s requests sandbox but is not a recognized sandboxed executor.", tool.name)

        # 4. Argument Tokenization & Sanitization (Future enhancement)
        # Here we could block specific arguments, e.g., 'rm -rf /' in terminal commands.
        self._check_argument_safety(tool, args)

    def _check_argument_safety(self, tool: "Tool", args: dict[str, Any]) -> None:
        """Heuristic checks for dangerous arguments."""
        if tool.name in {"terminal_cmd", "run_shell_command"}:
            cmd = str(args.get("command") or args.get("cmd") or "").lower()
            dangerous_tokens = [
                "rm -rf /",
                "mkfs",
                "dd if=",
                ":(){ :|:& };:",
                "shutdown",
                "reboot",
            ]
            for token in dangerous_tokens:
                if token in cmd:
                    raise ToolPolicyViolation(f"Command contains forbidden token '{token}'")

        if tool.name == "terminate_process":
            proc = str(args.get("process_name", "")).lower()
            protected_procs = ["explorer.exe", "svchost.exe", "system", "kernel"]
            if any(proc == p for p in protected_procs):
                raise ToolPolicyViolation(f"Cannot terminate protected system process: {proc}")
