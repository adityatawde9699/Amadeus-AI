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

    def __init__(self, is_development_mode: bool = False, strict_metadata: bool = False):
        self.is_development_mode = is_development_mode
        self._strict_metadata = strict_metadata

    def evaluate(self, tool: "Tool", args: dict[str, Any], context: RequestContext) -> None:
        """
        Evaluate if the tool can be safely executed in the given context.
        Raises ToolPolicyViolation if the execution is unsafe.

        The primary authorization boundary is the profile-rank check against the
        tool's declared ``min_permission``. This replaces the old, trivially
        bypassable command-substring denylist as a security control.
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

        # 0. Strict metadata gate (opt-in). Outside development, refuse tools whose
        #    security metadata was auto-derived rather than explicitly declared.
        if getattr(self, "_strict_metadata", False) and not getattr(capability, "explicit", True):
            if not self.is_development_mode:
                raise ToolPolicyViolation(
                    f"Tool {tool.name} lacks explicit security metadata (denied by policy)."
                )

        # 1. Minimum-permission check — the core authorization boundary.
        required = self._resolve_required_profile(capability)
        if not context.permissions.satisfies(required):
            raise ToolPolicyViolation(
                f"Tool {tool.name} requires '{required.value}' but session is "
                f"'{context.permissions.value}'."
            )

        # 2. Defense-in-depth: READ_ONLY never mutates state, regardless of metadata.
        if context.permissions == PermissionProfile.READ_ONLY:
            if capability.modifies_filesystem or capability.modifies_system_state:
                raise ToolPolicyViolation(
                    f"READ_ONLY session cannot execute mutating tool: {tool.name}"
                )
            if capability.risk_level in ("high", "critical"):
                raise ToolPolicyViolation(
                    f"READ_ONLY session cannot execute high-risk tool: {tool.name}"
                )

        # 3. Critical tools must declare confirmation so they cannot run implicitly.
        if (
            capability.risk_level == "critical"
            and not capability.requires_confirmation
            and not self.is_development_mode
        ):
            raise ToolPolicyViolation(
                f"Critical tool {tool.name} must declare requires_confirmation=True"
            )

        # 4. Sandbox sanity check.
        if getattr(capability, "sandbox_required", False) and "execute_python" not in tool.name:
            logger.warning(
                "Tool %s requests sandbox but is not a recognized sandboxed executor.", tool.name
            )

    @staticmethod
    def _resolve_required_profile(capability: Any) -> PermissionProfile:
        """Map a capability's min_permission string to a PermissionProfile."""
        raw = str(getattr(capability, "min_permission", "read_only")).lower()
        try:
            return PermissionProfile(raw)
        except ValueError:
            # Unknown value → fail closed at the highest privilege requirement.
            logger.warning("Unknown min_permission %r — requiring SYSTEM_FULL", raw)
            return PermissionProfile.SYSTEM_FULL
