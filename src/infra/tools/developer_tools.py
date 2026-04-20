"""
Developer tools for Amadeus AI Assistant.

Provides sandboxed Python code execution via Docker containers.
The sandbox is isolated, network-disabled, and resource-clamped —
see ``src.infra.sandbox.executor`` for security details.

Usage:
    from src.infra.tools.developer_tools import get_developer_tools

    for tool in get_developer_tools():
        registry.register(tool)
"""

import logging
from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

# Lazy-initialized sandbox executor (created on first tool call, not at import time)
_sandbox = None


def _get_sandbox():  # noqa: ANN202
    """Lazy-init the DockerSandboxExecutor so import never fails if Docker is absent."""
    global _sandbox  # noqa: PLW0603
    if _sandbox is None:
        from src.infra.sandbox.executor import DockerSandboxExecutor

        _sandbox = DockerSandboxExecutor()
    return _sandbox


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================


@tool(
    name="execute_python_script",
    description=(
        "Executes a Python script in a secure, sandboxed Docker environment "
        "without internet access. The script must be self-contained (stdlib only). "
        "Returns stdout on success or error details on failure. "
        "Trigger: 'run this code', 'calculate', 'analyze data', 'execute python'"
    ),
    category=ToolCategory.SYSTEM,
    parameters={
        "code": {
            "type": "string",
            "description": "The complete, self-contained Python script to execute.",
        },
    },
    requires_confirmation=True,
)
def execute_python_script(code: str | None = None, **kwargs: Any) -> str:
    """
    Execute a Python script in the Docker sandbox.

    Parameters
    ----------
    code:
        The Python script source code. Must be self-contained
        (only standard library imports allowed).

    Returns
    -------
    str:
        Execution result with stdout or error message.
    """
    script = code or kwargs.get("script", "")
    if not script or not script.strip():
        return "Error: No code provided. Please provide a Python script to execute."

    try:
        sandbox = _get_sandbox()
        result = sandbox.execute(script)

        if result["status"] == "success":
            output = result["output"].strip()
            if not output:
                return "Execution successful. The script produced no output."
            return f"Execution successful. Output:\n{output}"
        else:
            return (
                f"Execution failed ({result['status']}). Error:\n{result['output']}\n"
                "Fix the code and try again."
            )
    except Exception as e:
        logger.exception("Sandbox execution failed: %s", e)
        return (
            f"Sandbox unavailable: {e}\n"
            "Ensure Docker Desktop is running and the 'docker' Python package is installed."
        )


# =============================================================================
# TOOL COLLECTION
# =============================================================================


def get_developer_tools() -> list[Tool]:
    """Get all developer tools for manual registration."""
    tools = []
    for _name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools
