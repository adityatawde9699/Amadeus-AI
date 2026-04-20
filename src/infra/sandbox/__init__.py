"""
Docker Sandbox Infrastructure for Amadeus AI.

Provides isolated, ephemeral container execution for untrusted Python scripts.
"""

from src.infra.sandbox.executor import DockerSandboxExecutor

__all__ = ["DockerSandboxExecutor"]
