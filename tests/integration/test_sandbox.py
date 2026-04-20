"""
Integration tests for the Docker sandbox executor.

Prerequisites:
    - Docker Desktop (or daemon) must be running.
    - The ``docker`` Python package must be installed.

These tests are marked ``integration`` and will be auto-skipped if
the Docker daemon is not reachable.

Run:
    uv run pytest tests/integration/test_sandbox.py -v -m integration
"""

import time

import pytest


# ---------------------------------------------------------------------------
# Fixture: skip gracefully when Docker is not available
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sandbox():
    """Provide a DockerSandboxExecutor, skipping if Docker is unreachable."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as exc:
        pytest.skip(f"Docker daemon not available: {exc}")

    from src.infra.sandbox.executor import DockerSandboxExecutor

    return DockerSandboxExecutor()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_hello_world(sandbox):
    """A simple print() should succeed and capture stdout."""
    result = sandbox.execute('print("hello from sandbox")')
    assert result["status"] == "success"
    assert "hello from sandbox" in result["output"]


@pytest.mark.integration
def test_syntax_error(sandbox):
    """Invalid Python syntax should return an error status with traceback."""
    result = sandbox.execute("def broken(:\n    pass")
    assert result["status"] == "error"
    assert "SyntaxError" in result["output"]


@pytest.mark.integration
def test_infinite_loop_timeout(sandbox):
    """
    An infinite loop must be killed by the timeout without locking the host.

    We use a generous 20-second wall-clock assertion; the container itself
    has a 15-second timeout, so it should be killed well within that window.
    """
    start = time.monotonic()
    result = sandbox.execute("while True: pass", timeout=15)
    elapsed = time.monotonic() - start

    # The container should have been killed — either error or system_error
    assert result["status"] in ("error", "system_error"), (
        f"Expected error/system_error, got {result['status']}: {result['output'][:200]}"
    )
    # Ensure it didn't hang forever
    assert elapsed < 30, f"Sandbox took {elapsed:.1f}s — possible host lockup"


@pytest.mark.integration
def test_network_disabled(sandbox):
    """Network access should be blocked inside the container."""
    code = """
import urllib.request
try:
    urllib.request.urlopen("https://httpbin.org/get", timeout=5)
    print("NETWORK_ACCESSIBLE")
except Exception as e:
    print(f"NETWORK_BLOCKED: {e}")
"""
    result = sandbox.execute(code)
    # The script may succeed (print) or error — but it must NOT reach the internet
    full_output = result.get("output", "")
    assert "NETWORK_ACCESSIBLE" not in full_output, "Network should be blocked in sandbox"


@pytest.mark.integration
def test_no_output(sandbox):
    """A script that produces no output should still succeed."""
    result = sandbox.execute("x = 42")
    assert result["status"] == "success"
    assert result["output"].strip() == ""
