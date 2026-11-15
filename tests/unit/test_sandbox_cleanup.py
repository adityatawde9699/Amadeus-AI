"""DockerSandboxExecutor lifecycle with a fake Docker client (no daemon needed)."""

from __future__ import annotations

import sys
import types

import pytest


class _Container:
    short_id = "abc"
    id = "abc123"

    def __init__(self, exit_code=0, oom=False, remove_failures=0, logs=b""):
        self._exit, self._oom, self._fail, self._logs = exit_code, oom, remove_failures, logs
        self.attrs = {}
        self.removed = False
        self.remove_calls = 0

    def wait(self, timeout=None):
        return {"StatusCode": self._exit}

    def logs(self, stdout=True, stderr=True):
        return self._logs if stdout else b""

    def reload(self):
        self.attrs = {"State": {"OOMKilled": self._oom}}

    def remove(self, force=False):
        self.remove_calls += 1
        if self.remove_calls <= self._fail:
            raise RuntimeError("daemon busy")
        self.removed = True

    def kill(self):
        pass


class _Containers:
    def __init__(self, container, stale=()):
        self.container, self.stale, self.run_kwargs = container, list(stale), None

    def run(self, image, **kwargs):
        self.run_kwargs = kwargs
        return self.container

    def list(self, **kwargs):
        return self.stale


@pytest.fixture
def executor(monkeypatch):
    errors = types.SimpleNamespace(ImageNotFound=type("ImageNotFound", (Exception,), {}))
    errors.ContainerError = type("ContainerError", (Exception,), {})
    fake = types.SimpleNamespace(errors=errors)
    monkeypatch.setitem(sys.modules, "docker", fake)
    monkeypatch.setitem(sys.modules, "docker.errors", errors)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    from src.infra.sandbox.executor import DockerSandboxExecutor

    def make(container, stale=()):
        ex = DockerSandboxExecutor.__new__(DockerSandboxExecutor)
        ex.image = "img"
        ex.client = types.SimpleNamespace(
            containers=_Containers(container, stale),
            images=types.SimpleNamespace(get=lambda _i: None),
        )
        return ex

    return make


def test_container_is_labelled_and_removed(executor):
    c = _Container(logs=b"45\n")
    ex = executor(c)
    assert ex.execute("print(45)") == {"status": "success", "output": "45\n"}
    assert c.removed
    assert ex.client.containers.run_kwargs["labels"] == {"amadeus.sandbox": "1"}


def test_removal_is_retried_when_the_daemon_is_busy(executor):
    c = _Container(remove_failures=2)
    executor(c).execute("pass")
    assert c.removed and c.remove_calls == 3


def test_oom_kill_is_explained(executor):
    c = _Container(exit_code=137, oom=True)
    result = executor(c).execute("x = bytearray(10**9)")
    assert result["status"] == "error" and "memory limit" in result["output"]


def test_silent_nonzero_exit_is_not_an_empty_error(executor):
    result = executor(_Container(exit_code=2)).execute("import sys; sys.exit(2)")
    assert "exit code 2" in result["output"]


def test_stale_containers_are_swept(executor):
    stale = [_Container(), _Container()]
    executor(_Container(), stale)._sweep_stale()
    assert all(c.removed for c in stale)
