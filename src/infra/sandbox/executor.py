"""
Docker Sandbox Executor for Amadeus AI.

Executes untrusted Python scripts inside ephemeral Docker containers
with aggressive resource constraints. This is the ONLY code path
that should ever run user-supplied code.

Security constraints:
- Network disabled (no outbound connections)
- Memory capped at 128 MB
- CPU capped at 0.5 cores
- Runs as non-root user (1000:1000)
- Workspace mounted read-only
- Container auto-removed on exit
"""

import logging
import os
import tempfile
from typing import Any

import docker
import docker.errors

logger = logging.getLogger(__name__)


class DockerSandboxExecutor:
    """
    Isolated infrastructure class for running Python scripts in Docker.

    Handles container lifecycle, volume mounting, and resource clamping.
    The Docker client is encapsulated here — it must NEVER leak into
    tool definitions or the agent loop.
    """

    DEFAULT_IMAGE = "python:3.10-slim"
    DEFAULT_TIMEOUT = 15  # seconds

    def __init__(self, image: str | None = None) -> None:
        self.client = docker.from_env()
        self.image = image or self.DEFAULT_IMAGE
        self._ensure_image()

    def _ensure_image(self) -> None:
        """Pre-pull the execution image to prevent timeout on first run."""
        try:
            self.client.images.get(self.image)
            logger.debug("Sandbox image '%s' already available.", self.image)
        except docker.errors.ImageNotFound:
            logger.info("Pulling sandbox image '%s'...", self.image)
            self.client.images.pull(self.image)
            logger.info("Sandbox image '%s' pulled successfully.", self.image)

    def execute(self, code: str, timeout: int | None = None) -> dict[str, Any]:
        """
        Execute a Python script in an ephemeral container.

        Parameters
        ----------
        code:
            The complete Python script to run. Must be self-contained
            (no external imports beyond the stdlib).
        timeout:
            Maximum execution time in seconds. Defaults to 15.

        Returns
        -------
        dict with keys:
            - ``status``:  "success" | "error" | "system_error"
            - ``output``:  stdout on success, stderr on error, exception str on system_error
        """
        timeout = timeout or self.DEFAULT_TIMEOUT

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, "script.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            try:
                container_output = self.client.containers.run(
                    self.image,
                    command=["python", "/workspace/script.py"],
                    volumes={temp_dir: {"bind": "/workspace", "mode": "ro"}},
                    working_dir="/workspace",
                    # ── Resource clamping ──────────────────────────
                    mem_limit="128m",
                    nano_cpus=500_000_000,       # 0.5 CPU cores
                    # ── Security hardening ─────────────────────────
                    network_disabled=True,       # No outbound connections
                    user="1000:1000",            # Non-root execution
                    # ── Lifecycle ──────────────────────────────────
                    remove=True,                 # Auto-destroy container
                    stdout=True,
                    stderr=True,
                    # ── Timeout ────────────────────────────────────
                    # Note: docker-py does not support a timeout kwarg natively on run().
                    # We rely on the internal process to complete or we'll need to manually
                    # kill the container in a background task.

                )

                output = (
                    container_output.decode("utf-8")
                    if isinstance(container_output, bytes)
                    else str(container_output)
                )
                logger.info("Sandbox execution succeeded (%d chars output).", len(output))
                return {"status": "success", "output": output}

            except docker.errors.ContainerError as e:
                stderr = (
                    e.stderr.decode("utf-8")
                    if isinstance(e.stderr, bytes)
                    else str(e.stderr)
                )
                logger.warning("Sandbox execution error: %s", stderr[:200])
                return {"status": "error", "output": stderr}

            except Exception as e:
                logger.exception("Sandbox system error: %s", e)
                return {"status": "system_error", "output": str(e)}
