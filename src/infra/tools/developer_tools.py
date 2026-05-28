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
import subprocess
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
        "Executes a Python script in a secure, sandboxed Docker container with NO internet access. "
        "The script must be self-contained (Python standard library ONLY — no pip packages). "
        "Returns stdout on success or detailed error output on failure. Requires Docker Desktop running. "
        "Use this for: writing and running code, computing with Python, data analysis, complex calculations, "
        "generating sequences (Fibonacci, primes, etc.), file processing, algorithm implementation, "
        "or any task that requires actually executing code. "
        "Trigger: 'write and run python', 'run python code', 'execute this script', 'write a python script', "
        "'calculate using code', 'compute with python', 'run a script', 'write code', 'code this up'"
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
        logger.warning("Sandbox execution failed (Docker may not be running): %s", e)
        return (
            f"Sandbox unavailable: {e}\n"
            "Ensure Docker Desktop is running and the 'docker' Python package is installed."
        )


@tool(
    name="terminal_cmd",
    description=(
        "Executes a raw shell command directly on the host OS (PowerShell on Windows, bash on Linux/Mac). "
        "Has a 15-second timeout. Useful for network diagnostics (ping, ipconfig, nslookup), "
        "system info (systeminfo, hostname), or quick file operations. Requires confirmation. "
        "Trigger: 'run command', 'ping google.com', 'what is my IP', 'show network info'"
    ),
    category=ToolCategory.SYSTEM,
    parameters={
        "command": {
            "type": "string",
            "description": "The exact shell command to execute.",
        },
    },
    requires_confirmation=True,
)
def terminal_cmd(command: str | None = None, **kwargs: Any) -> str:
    """Execute a shell command on the host OS."""
    cmd = command or kwargs.get("cmd", "")
    if not cmd or not cmd.strip():
        return "Error: No command provided."
    
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return f"Command succeeded:\n{out}" if out else "Command succeeded with no output."
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return f"Command failed (exit {result.returncode}):\n{err}"
    except subprocess.TimeoutExpired:
        return f"Error: Command '{cmd}' timed out after 15 seconds."
    except Exception as e:
        logger.exception("terminal_cmd failed: %s", e)
        return f"Error executing command: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================


def get_developer_tools() -> list[Tool]:
    """Get all developer tools for manual registration."""
    return [
        execute_python_script._tool_metadata,  # type: ignore[attr-defined]
        terminal_cmd._tool_metadata,  # type: ignore[attr-defined]
    ]
