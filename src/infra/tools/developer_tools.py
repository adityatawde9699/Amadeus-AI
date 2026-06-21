"""
Developer tools for Amadeus AI Assistant.

Provides Python code execution ONLY via a hardened, ephemeral Docker container
(see ``src.infra.sandbox.executor``). There is no in-process fallback: the
previous "local" executor restricted CPython ``exec`` with a builtins blacklist,
which is trivially escapable and is not a security boundary. When Docker is
unavailable or ``SANDBOX_MODE=disabled``, code execution fails closed.

Usage:
    from src.infra.tools.developer_tools import get_developer_tools

    for tool in get_developer_tools():
        registry.register(tool)
"""

import logging
import shlex
from typing import Any

from src.infra.tools.base import Tool, ToolCapability, ToolCategory, tool


logger = logging.getLogger(__name__)


class SandboxUnavailableError(RuntimeError):
    """Raised when no secure sandbox backend is available to run code."""


# Lazy-initialized sandbox executor (created on first tool call, not at import time)
_sandbox = None


def _get_sandbox():
    """Return the hardened Docker sandbox, or raise SandboxUnavailableError.

    Fail closed: only ``SANDBOX_MODE=docker`` with a reachable Docker daemon
    yields an executor. ``disabled`` (the default) and any Docker error refuse
    to run code rather than silently degrading to an insecure backend.
    """
    global _sandbox
    if _sandbox is not None:
        return _sandbox

    from src.core.config import get_settings
    settings = get_settings()
    sandbox_mode = str(getattr(settings, "SANDBOX_MODE", "disabled")).lower()

    if sandbox_mode != "docker":
        raise SandboxUnavailableError(
            "Code execution is disabled (SANDBOX_MODE=disabled). Set "
            "SANDBOX_MODE=docker with Docker installed to enable the hardened sandbox."
        )

    try:
        import docker  # optional dep — see [sandbox-docker] extra

        client = docker.from_env()
        client.ping()
    except Exception as exc:
        raise SandboxUnavailableError(
            f"Docker sandbox requested but Docker is unavailable: {exc}"
        ) from exc

    from src.infra.sandbox.executor import DockerSandboxExecutor

    _sandbox = DockerSandboxExecutor()
    logger.info("Using hardened Docker Sandbox Executor.")
    return _sandbox


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================


@tool(
    name="execute_python_script",
    description=(
        "Executes a Python script in a hardened, network-isolated Docker sandbox. "
        "Requires Docker (SANDBOX_MODE=docker); if unavailable, execution is refused. "
        "The script must be self-contained (Python standard library ONLY — no pip packages). "
        "Returns stdout on success or detailed error output on failure. "
        "Use this for: writing and running code, computing with Python, data analysis, complex calculations, "
        "generating sequences (Fibonacci, primes, etc.), file processing, algorithm implementation, "
        "or any task that requires actually executing code. "
        "Trigger: 'write and run python', 'run python code', 'execute this script', 'write a python script', "
        "'calculate using code', 'compute with python', 'run a script', 'write code', 'code this up'"
    ),
    category=ToolCategory.DEVELOPER,
    parameters={
        "code": {
            "type": "string",
            "description": "The complete, self-contained Python script to execute.",
        },
    },
    requires_confirmation=True,
    capability=ToolCapability(
        name="execute_python_script",
        risk_level="critical",
        requires_confirmation=True,
        sandbox_required=True,
        requires_network=False,
        min_permission="system_full",
    ),
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
    except SandboxUnavailableError as e:
        # Fail closed — never execute code without the hardened sandbox.
        logger.warning("Code execution refused: %s", e)
        return f"Code execution unavailable: {e}"

    try:
        result = sandbox.execute(script)

        if result["status"] == "success":
            output = result["output"].strip()
            if not output:
                return "Execution successful. The script produced no output."
            return f"Execution successful. Output:\n{output}"
        return (
            f"Execution failed ({result['status']}). Error:\n{result['output']}\n"
            "Fix the code and try again."
        )
    except Exception as e:
        logger.warning("Sandbox execution failed: %s", e)
        return f"Code execution failed: {e}"


@tool(
    name="terminal_cmd",
    description=(
        "Executes a host OS command directly without shell expansion. "
        "Has a 15-second timeout. Useful for network diagnostics (ping, ipconfig, nslookup), "
        "system info (systeminfo, hostname), or quick file operations. Requires confirmation. "
        "Trigger: 'run command', 'ping google.com', 'what is my IP', 'show network info'"
    ),
    category=ToolCategory.DEVELOPER,
    parameters={
        "command": {
            "type": "string",
            "description": "The exact shell command to execute.",
        },
    },
    requires_confirmation=True,
    capability=ToolCapability(
        name="terminal_cmd",
        risk_level="critical",
        requires_confirmation=True,
        modifies_system_state=True,
        min_permission="system_full",
    ),
)
async def terminal_cmd(command: str | None = None, **kwargs: Any) -> str:
    """Execute a command on the host OS without invoking a shell."""
    import asyncio
    cmd = command or kwargs.get("cmd", "")
    if not cmd or not cmd.strip():
        return "Error: No command provided."

    try:
        args = shlex.split(cmd)
        if not args:
            return "Error: No command provided."

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except TimeoutError:
            process.kill()
            await process.wait()
            return f"Error: Command '{cmd}' timed out after 15 seconds."

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            return f"Command succeeded:\n{out}" if out else "Command succeeded with no output."
        return f"Command failed (exit {process.returncode}):\n{err or out}"
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
