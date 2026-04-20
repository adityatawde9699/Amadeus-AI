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
        "Set system volume to a percentage (0-100). "
        "Trigger: 'set volume to 50', 'volume 70%', 'increase volume', 'mute'"
    ),
    category=ToolCategory.SYSTEM,
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
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import-not-found]

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

        # Fallback: PowerShell nircmd-style
        try:
            clamped = max(0, min(100, level))
            # Use Windows built-in audio API via PowerShell
            ps_script = (
                f"$obj = New-Object -ComObject WScript.Shell; "
                f"$vol = {clamped}; "
                f"Add-Type -TypeDefinition '"
                f"using System.Runtime.InteropServices; "
                f"public class AudioHelper {{ "
                f"[DllImport(\"user32.dll\")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo); "
                f"}}'; "
            )
            # Simpler approach: nircmd or SoundVolumeView if available
            nircmd_result = subprocess.run(
                ["nircmd.exe", "setsysvolume", str(int(clamped * 655.35))],
                capture_output=True,
                timeout=5,
            )
            if nircmd_result.returncode == 0:
                return f"Volume set to {clamped}%."

            # Final fallback: PowerShell with WshShell (limited but works)
            ps = (
                f"[System.Media.SystemSounds]::Asterisk.Play(); "
                f"$wsh = New-Object -ComObject WScript.Shell; "
            )
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"$Volume = {clamped}; "
                    "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
                    "for($i=0;$i -lt 50;$i++){[System.Windows.Forms.SendKeys]::SendWait([char]174)}; "
                    f"for($i=0;$i -lt ($Volume/2);$i++){{[System.Windows.Forms.SendKeys]::SendWait([char]175)}}",
                ],
                timeout=10,
                capture_output=True,
            )
            return f"Volume adjusted to approximately {clamped}%."
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
    description="Get current system volume level. Trigger: 'what is the volume', 'current volume'",
    category=ToolCategory.SYSTEM,
)
def get_volume(**kwargs: Any) -> str:
    """Get current system volume."""
    if platform.system() == "Windows":
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL  # type: ignore[import-not-found]
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore[import-not-found]

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
        "Set screen brightness to a percentage (0-100). "
        "Trigger: 'set brightness to 70', 'brightness 50%', 'dim screen', 'increase brightness'"
    ),
    category=ToolCategory.SYSTEM,
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
        "Capture a screenshot of the current screen. "
        "Trigger: 'take screenshot', 'screenshot', 'capture screen', 'what is on my screen'"
    ),
    category=ToolCategory.SYSTEM,
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
        "List currently running/open applications and windows. "
        "Trigger: \"what's open\", 'show open apps', 'what programs are running', 'list windows'"
    ),
    category=ToolCategory.SYSTEM,
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


def get_system_control_tools() -> list[Tool]:
    """Get all system control tools."""
    tools = []
    for _name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools
