"""take_screenshot Linux fallbacks and get_gpu_stats without GPUtil."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.infra.tools import monitor_tools, system_control_tools


def _no_pil(monkeypatch):
    # make ``import PIL.ImageGrab`` fail so the CLI fallbacks run
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", None)


def test_wayland_tries_portal_tools_first_and_reports_success(monkeypatch, tmp_path):
    _no_pil(monkeypatch)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(system_control_tools.platform, "system", lambda: "Linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    tried: list[str] = []

    def fake_run(cmd, **_):
        tried.append(cmd[0])
        if cmd[0] == "grim":
            Path(cmd[-1]).write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(system_control_tools.subprocess, "run", fake_run)
    out = system_control_tools.take_screenshot(filename="shot")
    assert out.startswith("Screenshot saved to:") and out.endswith("shot.png")
    assert tried[:3] == ["gnome-screenshot", "spectacle", "grim"]


def test_wayland_failure_names_the_real_cause(monkeypatch, tmp_path):
    _no_pil(monkeypatch)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(system_control_tools.platform, "system", lambda: "Linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        system_control_tools.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )
    out = system_control_tools.take_screenshot()
    assert "Wayland" in out and "Pillow" not in out


def test_gpu_stats_fall_back_to_nvidia_smi(monkeypatch):
    monkeypatch.setitem(sys.modules, "GPUtil", None)
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="NVIDIA RTX 5050, 25, 2048, 8192, 45\n", stderr=""
        ),
    )
    out = monitor_tools.get_gpu_stats()
    assert "RTX 5050" in out and "25% load" in out and "25.0% memory" in out and "45" in out


def test_gpu_stats_without_any_source_is_plain(monkeypatch):
    monkeypatch.setitem(sys.modules, "GPUtil", None)
    monkeypatch.setattr("shutil.which", lambda _n: None)
    assert "No GPU statistics" in monitor_tools.get_gpu_stats()
