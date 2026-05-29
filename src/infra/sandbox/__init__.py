"""
Sandbox Infrastructure for Amadeus AI.

Provides isolated execution for untrusted Python scripts.
Supports both Docker-based and local multiprocessing-based execution.
"""

from src.infra.sandbox.executor import DockerSandboxExecutor
from src.infra.sandbox.local_executor import LocalSandboxExecutor

__all__ = ["DockerSandboxExecutor", "LocalSandboxExecutor"]
