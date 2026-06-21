"""
Sandbox Infrastructure for Amadeus AI.

Provides isolated execution for untrusted Python scripts via a hardened,
ephemeral Docker container. The previous in-process "local" executor was
removed — restricting CPython ``exec`` with a builtins blacklist is not a
security boundary.
"""

from src.infra.sandbox.executor import DockerSandboxExecutor


__all__ = ["DockerSandboxExecutor"]
