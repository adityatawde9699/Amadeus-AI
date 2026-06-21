"""
System control tools for Amadeus AI — Volume, Brightness, Screenshot, Running Apps.

These tools interface with the OS-level controls (Windows-first, cross-platform stubs).
"""

import logging
import platform
import subprocess
from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


# =============================================================================
# SCREENSHOT TOOL
# =============================================================================


@tool(
    name="take_screenshot",
    description=(
        "Captures a screenshot of the entire screen and saves it as a PNG file to the Downloads folder. "
        "Optionally accepts a custom filename (without extension). "
        "Trigger: 'take screenshot', 'capture my screen', 'screenshot', 'what is on my screen'"
    ),
    category=ToolCategory.OS_CONTROL,
    parameters={
        "filename": {
            "type": "string",
            "description": "Optional filename for the screenshot (without extension).",
        }
    },
)
def take_screenshot(filename: str | None = None, **kwargs: Any) -> str:
    """Capture a screenshot and save it to the desktop/downloads."""
    import datetime
    from pathlib import Path

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = filename or f"screenshot_{timestamp}"
    if not base_name.endswith(".png"):
        base_name += ".png"

    # Save to Downloads by default
    save_dir = Path.home() / "Downloads"
    save_dir.mkdir(exist_ok=True)
    save_path = save_dir / base_name

    try:
        import PIL.ImageGrab  # type: ignore[import-not-found]

        img = PIL.ImageGrab.grab()
        img.save(str(save_path))
        return f"Screenshot saved to: {save_path}"
    except ImportError:
        pass
    except Exception as e:
        logger.warning("PIL screenshot failed: %s", e)

    # Fallback: Windows snipping tool
    if platform.system() == "Windows":
        try:
            import ctypes
            import ctypes.wintypes

            # Use Windows API via ctypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            hwnd = user32.GetDesktopWindow()
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)

            hdc_src = user32.GetWindowDC(hwnd)
            hdc_dst = gdi32.CreateCompatibleDC(hdc_src)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_src, width, height)
            gdi32.SelectObject(hdc_dst, hbitmap)
            gdi32.BitBlt(hdc_dst, 0, 0, width, height, hdc_src, 0, 0, 0x00CC0020)

            # Save using Pillow if available
            try:
                import struct

                import PIL.Image

                bmpinfo = b"\x28\x00\x00\x00"  # BITMAPINFOHEADER size
                bmpinfo += struct.pack("ii", width, -height)
                bmpinfo += b"\x01\x00\x20\x00" + b"\x00" * 24

                buf = (ctypes.c_char * (width * height * 4))()
                gdi32.GetDIBits(hdc_dst, hbitmap, 0, height, buf, bmpinfo, 0)
                img = PIL.Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
                img.save(str(save_path))

                gdi32.DeleteObject(hbitmap)
                gdi32.DeleteDC(hdc_dst)
                user32.ReleaseDC(hwnd, hdc_src)

                return f"Screenshot saved to: {save_path}"
            except Exception:
                pass

            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_dst)
            user32.ReleaseDC(hwnd, hdc_src)
        except Exception as e:
            logger.warning("ctypes screenshot failed: %s", e)

        # Last resort: PowerShell
        try:
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.Screen]::PrimaryScreen | ForEach-Object {{ "
                f"$bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width, $_.Bounds.Height); "
                f"$g = [System.Drawing.Graphics]::FromImage($bmp); "
                f"$g.CopyFromScreen($_.Bounds.Location, [System.Drawing.Point]::Empty, $_.Bounds.Size); "
                f"$bmp.Save('{save_path}'); "
                f"$g.Dispose(); $bmp.Dispose() }}"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                check=False, capture_output=True, timeout=15,
            )
            if result.returncode == 0 and save_path.exists():
                return f"Screenshot saved to: {save_path}"
            return f"Screenshot failed (PowerShell exit code {result.returncode}). Install Pillow: pip install Pillow"
        except Exception as e:
            return f"Screenshot unavailable: {e}. Install Pillow: pip install Pillow"

    if platform.system() == "Linux":
        # Try the common CLI screenshot tools in order (XFCE first on Mint)
        candidates = [
            ["xfce4-screenshooter", "-f", "-s", str(save_path)],
            ["gnome-screenshot", "-f", str(save_path)],
            ["scrot", str(save_path)],
            ["import", "-window", "root", str(save_path)],  # ImageMagick
        ]
        for cmd in candidates:
            try:
                result = subprocess.run(cmd, check=False, capture_output=True, timeout=15)
                if result.returncode == 0 and save_path.exists():
                    return f"Screenshot saved to: {save_path}"
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.warning("Screenshot via %s failed: %s", cmd[0], e)
        return (
            "Screenshot failed. Install Pillow (pip install Pillow) or a CLI tool "
            "(xfce4-screenshooter, gnome-screenshot, scrot)."
        )

    return "Screenshot requires Pillow: pip install Pillow"


# =============================================================================
# RUNNING APPS TOOL
# =============================================================================


@tool(
    name="list_open_apps",
    description=(
        "Lists all currently running user-facing applications (excludes system processes). "
        "Shows up to 20 app names. Works on Windows, macOS, and Linux. "
        "Trigger: 'what apps are open', 'show running programs', 'list open windows'"
    ),
    category=ToolCategory.OS_CONTROL,
)
def list_open_apps(**kwargs: Any) -> str:
    """List all currently open/visible application windows."""
    if platform.system() == "Windows":
        try:
            import ctypes

            import psutil

            # Use psutil to get named processes with windows
            app_processes = []
            seen_names = set()
            for proc in psutil.process_iter(["pid", "name", "status"]):
                try:
                    if proc.info["status"] == psutil.STATUS_RUNNING:
                        name = proc.info["name"]
                        if name and name not in seen_names and not name.startswith("svchost"):
                            # Filter to user-facing apps (heuristic: has .exe, not a system process)
                            if name.endswith(".exe"):
                                clean_name = name.replace(".exe", "")
                                seen_names.add(name)
                                app_processes.append(clean_name)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if app_processes:
                apps_str = ", ".join(sorted(app_processes[:20]))
                return f"Open applications: {apps_str}"
            return "No user applications detected."
        except Exception as e:
            return f"Could not list apps: {e}"

        try:
            # Alternative: enumerate windows via EnumWindows
            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible

            titles: list[str] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            def foreach_window(hwnd: Any, lParam: Any) -> bool:
                if IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(512)
                    GetWindowText(hwnd, buf, 512)
                    title = buf.value.strip()
                    if title:
                        titles.append(title)
                return True

            EnumWindows(foreach_window, 0)
            if titles:
                titles_str = "\n".join(f"  • {t}" for t in sorted(set(titles))[:20])
                return f"Open windows:\n{titles_str}"
            return "No visible windows found."
        except Exception as e:
            return f"Window enumeration failed: {e}"

    elif platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of every process whose background only is false'],
                check=False, capture_output=True, text=True, timeout=5,
            )
            apps = result.stdout.strip().split(", ")
            return "Open apps: " + ", ".join(apps)
        except Exception as e:
            return f"Could not list apps on macOS: {e}"

    elif platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-l"], check=False, capture_output=True, text=True, timeout=5
            )
            titles = [line.split(None, 3)[-1] for line in result.stdout.splitlines() if line]
            if titles:
                return "Open windows: " + "; ".join(titles[:15])
        except FileNotFoundError:
            pass
        except Exception as e:
            return f"Could not list apps on Linux: {e}"

        # Fallback: psutil process scan (works without wmctrl/X11)
        try:
            import psutil

            seen = set()
            for proc in psutil.process_iter(["name", "username"]):
                try:
                    name = proc.info["name"]
                    if name and name not in seen:
                        seen.add(name)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            apps = sorted(seen)[:20]
            return "Running processes: " + ", ".join(apps)
        except Exception as e:
            return f"Could not list apps on Linux: {e}. Try: sudo apt install wmctrl"

    return "Listing open apps not supported on this platform."


# =============================================================================
# TOOL COLLECTION
# =============================================================================


@tool(
    name="terminate_process",
    description=(
        "Forcefully terminates a running process by its name or PID. "
        "Use this to close unresponsive apps or stop background tasks. "
        "Trigger: 'kill chrome', 'stop process 1234', 'close unresponsive app', 'terminate notepad'"
    ),
    category=ToolCategory.OS_CONTROL,
    parameters={
        "process_name": {
            "type": "string",
            "description": "Name of the process (e.g., 'chrome.exe') or PID.",
        }
    },
    requires_confirmation=True,
)
def terminate_process(process_name: str, **kwargs: Any) -> str:
    """Terminate a process by name or PID."""
    import psutil

    try:
        # Check if it's a PID
        if process_name.isdigit():
            pid = int(process_name)
            proc = psutil.Process(pid)
            proc.terminate()
            return f"Process with PID {pid} ({proc.name()}) has been terminated."

        # Search by name
        terminated_count = 0
        for proc in psutil.process_iter(["pid", "name"]):
            if process_name.lower() in proc.info["name"].lower():
                proc.terminate()
                terminated_count += 1

        if terminated_count > 0:
            return f"Successfully terminated {terminated_count} process(es) matching '{process_name}'."
        return f"No processes found matching '{process_name}'."
    except Exception as e:
        return f"Error terminating process: {e}"


@tool(
    name="launch_app",
    description=(
        "Launches an application by name or path. "
        "On Windows, it can use the 'start' command for registered apps. "
        "Trigger: 'open calculator', 'start notepad', 'launch vscode', 'run chrome'"
    ),
    category=ToolCategory.OS_CONTROL,
    parameters={
        "app_name": {
            "type": "string",
            "description": "Name of the app or full path to executable.",
        }
    },
    requires_confirmation=True,
)
def launch_app(app_name: str, **kwargs: Any) -> str:
    """Launch an application."""
    import subprocess

    if platform.system() == "Windows":
        try:
            # Try to start using shell 'start' command which handles PATH and associations
            # Use 'cmd /c start' with explicit argument list — NO shell=True
            subprocess.Popen(["cmd", "/c", "start", "", app_name])
            return f"Attempting to launch '{app_name}'..."
        except Exception as e:
            return f"Failed to launch '{app_name}': {e}"
    elif platform.system() == "Darwin":
        try:
            subprocess.Popen(["open", "-a", app_name])
            return f"Attempting to launch '{app_name}' on macOS..."
        except Exception as e:
            return f"Failed to launch '{app_name}': {e}"
    elif platform.system() == "Linux":
        try:
            subprocess.Popen([app_name], start_new_session=True)
            return f"Attempting to launch '{app_name}' on Linux..."
        except Exception as e:
            return f"Failed to launch '{app_name}': {e}"

    return f"Launch app not supported on {platform.system()}."


def get_system_control_tools() -> list[Tool]:
    """Get all system control tools."""
    return [
        take_screenshot._tool_metadata,  # type: ignore[attr-defined]
        list_open_apps._tool_metadata,  # type: ignore[attr-defined]
        terminate_process._tool_metadata,  # type: ignore[attr-defined]
        launch_app._tool_metadata,  # type: ignore[attr-defined]
    ]
