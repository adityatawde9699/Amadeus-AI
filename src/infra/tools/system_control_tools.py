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
# VOLUME CONTROL
# =============================================================================


@tool(
    name="set_volume",
    description=(
        "Sets the system audio volume to a percentage (0-100). "
        "Special values: -1 to mute, -2 to unmute. "
        "Works on Windows (via pycaw), Linux (amixer), and macOS. "
        "Trigger: 'set volume to 50', 'volume 70%', 'mute', 'unmute', 'make it louder'"
    ),
    category=ToolCategory.OS_CONTROL,
    parameters={
        "level": {
            "type": "integer",
            "description": "Volume level 0-100. Use -1 to mute, -2 to unmute.",
        }
    },
)
def set_volume(level: int = 50, **kwargs: Any) -> str:
    """Set system volume using OS-native commands."""
    # Support keyword aliases: 'volume', 'percent', 'value'
    level = kwargs.get("volume", kwargs.get("percent", kwargs.get("value", level)))
    try:
        level = int(level)
    except (ValueError, TypeError):
        return "Error: volume level must be an integer between 0 and 100."

    if platform.system() == "Windows":
        try:
            # Use pycaw if available (best approach on Windows)
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL  # type: ignore[import-not-found]
            from pycaw.pycaw import (  # type: ignore[import-not-found]
                AudioUtilities,
                IAudioEndpointVolume,
            )

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume_ctrl = cast(interface, POINTER(IAudioEndpointVolume))

            if level == -1:  # mute
                volume_ctrl.SetMute(1, None)
                return "System muted."
            if level == -2:  # unmute
                volume_ctrl.SetMute(0, None)
                return "System unmuted."

            clamped = max(0, min(100, level))
            scalar = clamped / 100.0
            volume_ctrl.SetMasterVolumeLevelScalar(scalar, None)
            return f"Volume set to {clamped}%."
        except ImportError:
            pass  # fall through to PowerShell
        except Exception as e:
            logger.warning("pycaw volume control failed: %s", e)

        # Final fallback: PowerShell with Audio API
        try:
            clamped = max(0, min(100, level))
            ps_script = """
$code = @"
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
    int f(); int g(); int h(); int i();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pEventContext);
    int j();
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int k(); int l(); int m(); int n();
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pEventContext);
    int GetMute(out bool pbMute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
    int Activate(ref System.Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
    int f();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] public class MMDeviceEnumeratorComObject { }
public class Audio {
    static IAudioEndpointVolume Vol() {
        var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev = null;
        enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
        IAudioEndpointVolume epv = null;
        var epvid = typeof(IAudioEndpointVolume).GUID;
        dev.Activate(ref epvid, 23, 0, out epv);
        return epv;
    }
    public static float Volume {
        get { float v = -1; Vol().GetMasterVolumeLevelScalar(out v); return v; }
        set { Vol().SetMasterVolumeLevelScalar(value, System.Guid.Empty); }
    }
    public static bool Mute {
        get { bool m = false; Vol().GetMute(out m); return m; }
        set { Vol().SetMute(value, System.Guid.Empty); }
    }
}
"@
Add-Type -TypeDefinition $code
"""
            if level == -1:
                ps_script += "\n[Audio]::Mute = $true"
            elif level == -2:
                ps_script += "\n[Audio]::Mute = $false"
            else:
                ps_script += f"\n[Audio]::Volume = {clamped / 100.0}"

            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                timeout=10,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return f"Volume adjusted to {clamped}%." if level >= 0 else "Mute state toggled."
            return f"Failed to set volume via PowerShell. Output: {result.stderr.strip() or result.stdout.strip()}"
        except Exception as e:
            return f"Failed to set volume: {e}"

    elif platform.system() == "Linux":
        try:
            clamped = max(0, min(100, level))
            subprocess.run(["amixer", "sset", "Master", f"{clamped}%"], capture_output=True, timeout=5)
            return f"Volume set to {clamped}%."
        except Exception as e:
            return f"Failed to set volume on Linux: {e}"

    elif platform.system() == "Darwin":
        try:
            clamped = max(0, min(100, level))
            subprocess.run(["osascript", "-e", f"set volume output volume {clamped}"], timeout=5)
            return f"Volume set to {clamped}%."
        except Exception as e:
            return f"Failed to set volume on macOS: {e}"

    return f"Volume control not supported on {platform.system()}."


@tool(
    name="get_volume",
    description=(
        "Returns the current system volume level as a percentage (0-100) and muted state. "
        "Trigger: 'what is the volume', 'current volume', 'how loud is it', 'am I muted'"
    ),
    category=ToolCategory.OS_CONTROL,
)
def get_volume(**kwargs: Any) -> str:
    """Get current system volume."""
    if platform.system() == "Windows":
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL  # type: ignore[import-not-found]
            from pycaw.pycaw import (  # type: ignore[import-not-found]
                AudioUtilities,
                IAudioEndpointVolume,
            )

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume_ctrl = cast(interface, POINTER(IAudioEndpointVolume))
            current = round(volume_ctrl.GetMasterVolumeLevelScalar() * 100)
            muted = volume_ctrl.GetMute()
            status = " (muted)" if muted else ""
            return f"Current volume: {current}%{status}"
        except ImportError:
            return "Volume info requires pycaw: pip install pycaw"
        except Exception as e:
            return f"Could not get volume: {e}"
    return "Volume query not supported on this platform."


# =============================================================================
# BRIGHTNESS CONTROL
# =============================================================================


@tool(
    name="set_brightness",
    description=(
        "Sets screen brightness to a percentage (0-100). "
        "Works on Windows (WMI), Linux (xrandr), and macOS. May require admin rights on some systems. "
        "Trigger: 'set brightness to 70', 'brightness 50%', 'dim screen', 'make screen brighter'"
    ),
    category=ToolCategory.OS_CONTROL,
    parameters={
        "level": {
            "type": "integer",
            "description": "Brightness level 0-100.",
        }
    },
)
def set_brightness(level: int = 70, **kwargs: Any) -> str:
    """Set screen brightness."""
    level = kwargs.get("brightness", kwargs.get("percent", kwargs.get("value", level)))
    try:
        level = int(level)
        clamped = max(0, min(100, level))
    except (ValueError, TypeError):
        return "Error: brightness level must be an integer between 0 and 100."

    if platform.system() == "Windows":
        try:
            import wmi  # type: ignore[import-not-found]
            c = wmi.WMI(namespace="wmi")
            methods = c.WmiMonitorBrightnessMethods()[0]
            methods.WmiSetBrightness(clamped, 0)
            return f"Brightness set to {clamped}%."
        except ImportError:
            pass
        except Exception as e:
            logger.warning("WMI brightness control failed: %s", e)

        # PowerShell fallback
        try:
            ps_cmd = (
                f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{clamped})"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return f"Brightness set to {clamped}%."
            return f"Brightness adjustment attempted (may require admin rights). Level: {clamped}%."
        except Exception as e:
            return f"Failed to set brightness: {e}"

    elif platform.system() == "Linux":
        try:
            # Try xrandr
            result = subprocess.run(
                ["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=5
            )
            monitors = [
                line.split()[-1]
                for line in result.stdout.splitlines()
                if "+" in line
            ]
            for monitor in monitors:
                subprocess.run(
                    ["xrandr", "--output", monitor, "--brightness", str(clamped / 100)],
                    timeout=5,
                )
            return f"Brightness set to {clamped}%."
        except Exception as e:
            return f"Failed to set brightness on Linux: {e}"

    elif platform.system() == "Darwin":
        try:
            # brightness 0.0-1.0
            subprocess.run(
                ["brightness", str(clamped / 100)],
                timeout=5,
            )
            return f"Brightness set to {clamped}%."
        except Exception as e:
            return f"Failed to set brightness on macOS: {e}"

    return f"Brightness control not supported on {platform.system()}."


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
                ["powershell", "-Command", ps_cmd], capture_output=True, timeout=15
            )
            if result.returncode == 0 and save_path.exists():
                return f"Screenshot saved to: {save_path}"
            return f"Screenshot failed (PowerShell exit code {result.returncode}). Install Pillow: pip install Pillow"
        except Exception as e:
            return f"Screenshot unavailable: {e}. Install Pillow: pip install Pillow"

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
                capture_output=True, text=True, timeout=5,
            )
            apps = result.stdout.strip().split(", ")
            return "Open apps: " + ", ".join(apps)
        except Exception as e:
            return f"Could not list apps on macOS: {e}"

    elif platform.system() == "Linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-l"], capture_output=True, text=True, timeout=5
            )
            titles = [line.split(None, 3)[-1] for line in result.stdout.splitlines() if line]
            return "Open windows: " + "; ".join(titles[:15])
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
        set_volume._tool_metadata,  # type: ignore[attr-defined]
        get_volume._tool_metadata,  # type: ignore[attr-defined]
        set_brightness._tool_metadata,  # type: ignore[attr-defined]
        take_screenshot._tool_metadata,  # type: ignore[attr-defined]
        list_open_apps._tool_metadata,  # type: ignore[attr-defined]
        terminate_process._tool_metadata,  # type: ignore[attr-defined]
        launch_app._tool_metadata,  # type: ignore[attr-defined]
    ]
