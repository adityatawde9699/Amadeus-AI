"""
Docker Sandbox Executor for Amadeus AI.

Executes untrusted Python scripts inside ephemeral Docker containers
with aggressive resource constraints. This is the ONLY code path
that should ever run user-supplied code.

Security constraints:
- Network disabled (no outbound connections)
- Read-only root filesystem; only a small writable tmpfs at /tmp
- All Linux capabilities dropped; no-new-privileges
- Memory + swap capped (128 MB); CPU capped at 0.5 cores; PID-limited
- Runs as non-root user (1000:1000)
- Workspace mounted read-only
- Pinned image; container force-killed on timeout and auto-removed
"""

import logging
import os
import tempfile
from typing import Any

# NOTE: ``docker`` is an optional dependency (the ``[sandbox-docker]`` extra and
# ENABLE_DOCKER_SANDBOX flag). It is imported lazily inside the methods that use
# it so this module — and the default install — import cleanly without Docker.

logger = logging.getLogger(__name__)


class DockerSandboxExecutor:
    """
    Isolated infrastructure class for running Python scripts in Docker.

    Handles container lifecycle, volume mounting, and resource clamping.
    The Docker client is encapsulated here — it must NEVER leak into
    tool definitions or the agent loop.
    """

    # Pinned to a specific patch version (not ``latest``). For stronger supply-
    # chain guarantees, operators should pin by digest via the ``image`` ctor arg
    # or the SANDBOX_IMAGE setting, e.g. "python:3.10.14-slim@sha256:<digest>".
    DEFAULT_IMAGE = "python:3.10.14-slim"
    DEFAULT_TIMEOUT = 15  # seconds

    def __init__(self, image: str | None = None) -> None:
        import docker  # optional dep — see [sandbox-docker] extra

        self.client = docker.from_env()
        self.image = image or self.DEFAULT_IMAGE
        self._ensure_image()

    def _ensure_image(self) -> None:
        """Pre-pull the execution image to prevent timeout on first run."""
        import docker.errors  # optional dep — see [sandbox-docker] extra

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
        import docker.errors  # optional dep — see [sandbox-docker] extra

        timeout = timeout or self.DEFAULT_TIMEOUT

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = os.path.join(temp_dir, "script.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            container = None
            try:
                # Run detached so we can enforce a hard wall-clock timeout and
                # force-kill an overrunning container (docker-py's run() has no
                # native timeout).
                container = self.client.containers.run(
                    self.image,
                    command=["python", "/workspace/script.py"],
                    volumes={temp_dir: {"bind": "/workspace", "mode": "ro"}},
                    working_dir="/workspace",
                    # ── Resource clamping ──────────────────────────
                    mem_limit="128m",
                    memswap_limit="128m",        # no swap beyond the mem limit
                    nano_cpus=500_000_000,       # 0.5 CPU cores
                    pids_limit=128,              # fork-bomb guard
                    # ── Security hardening ─────────────────────────
                    network_disabled=True,       # No outbound connections
                    network_mode="none",
                    user="1000:1000",            # Non-root execution
                    read_only=True,             # Read-only root filesystem
                    cap_drop=["ALL"],           # Drop all Linux capabilities
                    security_opt=["no-new-privileges"],
                    # Minimal writable scratch space (capped, non-exec).
                    tmpfs={"/tmp": "rw,size=16m,nosuid,nodev,noexec"},
                    # ── Lifecycle ──────────────────────────────────
                    detach=True,
                    stdout=True,
                    stderr=True,
                )

                try:
                    exit_info = container.wait(timeout=timeout)
                    status_code = exit_info.get("StatusCode", 0) if isinstance(exit_info, dict) else 0
                    stdout = container.logs(stdout=True, stderr=False)
                    stderr = container.logs(stdout=False, stderr=True)
                    out = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else str(stdout)
                    err = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)

                    if status_code == 0:
                        logger.info("Sandbox execution succeeded (%d chars output).", len(out))
                        return {"status": "success", "output": out}
                    logger.warning("Sandbox execution error (exit %s): %s", status_code, err[:200])
                    return {"status": "error", "output": err or out}
                except Exception as wait_exc:
                    # Timeout or wait failure → force kill.
                    logger.warning("Sandbox timed out / wait failed: %s — killing container", wait_exc)
                    try:
                        container.kill()
                    except Exception:
                        pass
                    return {
                        "status": "error",
                        "output": f"Execution timed out after {timeout} seconds.",
                    }

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

            finally:
                # Always remove the (detached) container.
                if container is not None:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
