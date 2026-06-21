"""
System tools for Amadeus AI Assistant.

Includes application management, file operations, and process control.
Migrated from system_controls.py to Clean Architecture structure.
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import psutil

from src.infra.system.app_registry import AppRegistry
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


# Initialize global registry locally for tools since tool execution happens statically
# In a fully DI environment, this might be injected into ToolConfig
app_registry = AppRegistry()

# =============================================================================
# PATH SANDBOX HELPER (CQ-01, CQ-02)
# =============================================================================


def _assert_in_allowed_dirs(path):
    """Return an error string if *path* is outside SEARCH_ALLOWED_DIRS, else None.

    CQ-01 / CQ-02: Prevents copy_file / move_file / create_folder from writing
    to arbitrary filesystem locations when the LLM is tricked via prompt injection.
    """
    from src.core.config import get_settings
    settings = get_settings()
    allowed_roots = [Path(d).expanduser().resolve() for d in settings.SEARCH_ALLOWED_DIRS]
    try:
        resolved = path.resolve()
    except Exception:
        return f"Access denied: cannot resolve path '{path}'."
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return None  # inside an allowed directory
        except ValueError:
            continue
    roots_str = ", ".join(str(r) for r in allowed_roots)
    return (
        f"Access denied: '{resolved}' is outside the allowed directories ({roots_str})."
    )




# =============================================================================
# APPLICATION TOOLS
# =============================================================================


@tool(
    name="open_program",
    description=(
        "Launches any installed desktop application by name using fuzzy matching. "
        "Works with all installed programs (Chrome, VSCode, Word, VLC, Spotify, etc.). "
        "Uses the AppRegistry to find the closest match for the given name. "
        "Trigger: 'open chrome', 'launch vscode', 'start spotify', 'open vlc'"
    ),
    category=ToolCategory.APP_CONTROL,
    parameters={"app_name": {"type": "string", "description": "Application name to open"}},
)
def open_program(
    app_name: str | None = None, program_name: str | None = None, **kwargs: Any
) -> str:
    """Open an application using the dynamic AppRegistry with fuzzy matching."""
    target_app = app_name or program_name or kwargs.get("name")
    if not target_app:
        return "Error: No application name provided."

    # Direct path fallback for common apps
    _COMMON_APPS = {
        "vlc": r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
    }
    lower = target_app.lower()
    if lower in _COMMON_APPS:
        path = _COMMON_APPS[lower]
        try:
            if platform.system() == "Windows":
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except (FileNotFoundError, OSError):
                    subprocess.Popen([path], shell=False)
                return f"Opening {target_app}..."
        except Exception:
            pass  # fall through to registry

    # Direct $PATH lookup — fastest and most precise route
    direct = shutil.which(lower)
    if direct:
        app_exec = direct
    else:
        app_exec = app_registry.get_executable(target_app, score_cutoff=75)
    if not app_exec:
        return (
            f"Cannot find '{target_app}' on this system. "
            "You may need to trigger a system scan using `scan_system_applications`."
        )

    logger.info("Opening application: %s (%s)", target_app, app_exec)

    try:
        if platform.system() == "Windows":
            try:
                os.startfile(app_exec)  # type: ignore[attr-defined]
            except (FileNotFoundError, OSError):
                subprocess.Popen([app_exec], shell=False)
        elif platform.system() == "Darwin":
            # On Mac, app_exec from registry is absolute path to .app bundle
            subprocess.Popen(["open", app_exec])
        elif platform.system() == "Linux":
            # Tier 1: Check if app_exec is directly in $PATH (most reliable)
            resolved = shutil.which(app_exec)
            if resolved:
                subprocess.Popen(
                    [resolved],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Tier 2: Try app_exec as-is (may be an absolute path from Exec=)
                try:
                    subprocess.Popen(
                        app_exec.split(),
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except (FileNotFoundError, PermissionError) as exc:
                    return (
                        f"Could not launch '{target_app}': {exc}. "
                        "Try running `scan_system_applications` to rebuild the app list."
                    )

        else:
            return f"Unsupported operating system: {platform.system()}"

        return f"Opening {target_app}..."

    except Exception as e:
        logger.exception("Error launching app %s: %s", target_app, e)
        return f"Failed to open {target_app}: {e}"


@tool(
    name="scan_system_applications",
    description=(
        "Forces a deep scan of the local OS to discover all installed applications "
        "and rebuilds the internal app cache. Run this after installing new software "
        "so Amadeus can find and launch it. "
        "Trigger: 'scan apps', 'refresh app list', 'find new programs', 'update app registry'"
    ),
    category=ToolCategory.APP_CONTROL,
    parameters={},
)
def scan_system_applications(**kwargs: Any) -> str:
    """Re-scans the system to update the application registry."""
    try:
        logger.info("Executing system-wide application scan manually via tool.")
        discovered = app_registry.scan_and_cache()
        return f"Successfully scanned the system and found {len(discovered)} applications."
    except Exception as e:
        return f"Failed to scan system applications: {e}"


@tool(
    name="terminate_program",
    description=(
        "Terminates all running processes matching the given name. WARNING: kills ALL matches "
        "(e.g., 'chrome' will close every Chrome window). Requires confirmation before executing. "
        "Trigger: 'close chrome', 'kill notepad', 'stop vlc', 'terminate firefox'"
    ),
    category=ToolCategory.APP_CONTROL,
    parameters={"process_name": {"type": "string", "description": "Process name to terminate"}},
    requires_confirmation=True,
)
def terminate_program(
    process_name: str | None = None, app_name: str | None = None, **kwargs: Any
) -> str:
    """Terminate all processes matching the name."""
    target = process_name or app_name or kwargs.get("name")
    if not target:
        return "Error: No process name provided."

    try:
        count = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if target.lower() in proc.info["name"].lower():
                    psutil.Process(proc.info["pid"]).terminate()
                    count += 1
                    logger.info(
                        "Terminated: %s (PID: %s)", proc.info["name"], proc.info["pid"]
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if count > 0:
            return f"Terminated {count} process(es) matching '{target}'"
        return f"No processes found matching '{target}'"

    except Exception as e:
        logger.exception("Error terminating '%s': %s", target, e)
        return f"Error terminating process: {e}"


# =============================================================================
# FILE OPERATION TOOLS
# =============================================================================


@tool(
    name="search_file",
    description=(
        "Searches for files by name or pattern across user directories (Documents, Desktop, Downloads). "
        "Returns file paths for matches. Supports glob patterns (e.g., '*.pdf'). "
        "Does NOT search hidden directories or system folders for security. "
        "Trigger: 'find file report.pdf', 'where is my resume', 'locate *.xlsx', 'search for notes'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={"file_name": {"type": "string", "description": "File name or pattern to search"}},
)
def search_file(file_name: str | None = None, name: str | None = None, **kwargs: Any) -> str:
    """
    Search for files using glob patterns within the configured allowlist only.

    The search is restricted to ``settings.SEARCH_ALLOWED_DIRS`` (default:
    ~/Documents, ~/Desktop, ~/Downloads).  Hidden directories — any directory
    component whose name starts with '.' — are always skipped to prevent
    sensitive paths like ~/.ssh or ~/.aws from leaking into the LLM context.
    """
    target = file_name or name or kwargs.get("query")
    if not target:
        return "Error: No file name provided."

    from src.core.config import get_settings

    settings = get_settings()
    max_results = settings.FILE_SEARCH_MAX_RESULTS
    pattern = f"*{target}*" if "*" not in target else target

    # Expand each allowed directory (handles ~)
    search_roots = [Path(d).expanduser() for d in settings.SEARCH_ALLOWED_DIRS]
    # Only keep roots that actually exist on this system
    search_roots = [r for r in search_roots if r.is_dir()]

    if not search_roots:
        return (
            "Search is restricted to configured directories, but none of them exist "
            "on this system. Check SEARCH_ALLOWED_DIRS in your .env file."
        )

    logger.info("Searching for '%s' across %d allowed dirs", target, len(search_roots))

    found_files: list[Path] = []

    for root in search_roots:
        try:
            for file_path in root.rglob(pattern):
                # Skip any path that has a hidden directory component
                if any(part.startswith(".") for part in file_path.parts):
                    continue
                if file_path.is_file():
                    found_files.append(file_path)
                    if len(found_files) >= max_results:
                        break
        except PermissionError:
            pass

        if len(found_files) >= max_results:
            break

    if not found_files:
        return f"No files found matching '{target}' in the allowed search directories."

    result_lines = [f"Found {len(found_files)} file(s) matching '{target}':"]
    for f in found_files:
        result_lines.append(f"  - {f}")
    return "\n".join(result_lines)


@tool(
    name="copy_file",
    description=(
        "Copies a file from source path to destination path. Both paths must be within "
        "allowed directories (Documents, Desktop, Downloads). Creates parent directories if needed. "
        "Trigger: 'copy file X to Y', 'duplicate this file', 'make a copy of'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={
        "source_path": {"type": "string", "description": "Source file path"},
        "destination_path": {"type": "string", "description": "Destination file path"},
    },
)
def copy_file(
    source_path: str | None = None, destination_path: str | None = None, **kwargs: Any
) -> str:
    """Copy a file from source to destination."""
    src = source_path or kwargs.get("source") or kwargs.get("src")
    dst = destination_path or kwargs.get("destination") or kwargs.get("dest")

    if not src or not dst:
        return "Error: Source and destination paths required."

    try:
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        # CQ-01: Sandbox both source and destination
        for label, p in (("source", src_path), ("destination", dst_path)):
            err = _assert_in_allowed_dirs(p)
            if err:
                return f"copy_file {label} - {err}"

        if not src_path.is_file():
            return f"Source file does not exist: {src}"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)

        logger.info("File copied: %s -> %s", src_path, dst_path)
        return f"File copied to {dst_path}"

    except Exception as e:
        logger.exception("Error copying file: %s", e)
        return f"Error copying file: {e}"


@tool(
    name="move_file",
    description=(
        "Moves a file from source path to destination path (cut + paste). Both paths must be "
        "within allowed directories. Creates parent directories if needed. "
        "Trigger: 'move file X to Y', 'relocate this file', 'transfer file to Downloads'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={
        "source_path": {"type": "string", "description": "Source file path"},
        "destination_path": {"type": "string", "description": "Destination file path"},
    },
)
def move_file(
    source_path: str | None = None, destination_path: str | None = None, **kwargs: Any
) -> str:
    """Move a file from source to destination."""
    src = source_path or kwargs.get("source")
    dst = destination_path or kwargs.get("destination")

    if not src or not dst:
        return "Error: Source and destination paths required."

    try:
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        # CQ-01: Sandbox both source and destination
        for label, p in (("source", src_path), ("destination", dst_path)):
            err = _assert_in_allowed_dirs(p)
            if err:
                return f"move_file {label} - {err}"

        if not src_path.is_file():
            return f"Source file does not exist: {src}"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))

        logger.info("File moved: %s -> %s", src_path, dst_path)
        return f"File moved to {dst_path}"

    except Exception as e:
        logger.exception("Error moving file: %s", e)
        return f"Error moving file: {e}"


@tool(
    name="delete_file",
    description=(
        "Deletes a file permanently (a backup copy is saved to the temp folder for recovery). "
        "Requires confirmation before executing. "
        "Trigger: 'delete file X', 'remove this file', 'trash report.pdf'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={"file_path": {"type": "string", "description": "Path to file to delete"}},
    requires_confirmation=True,
)
def delete_file(file_path: str | None = None, path: str | None = None, **kwargs: Any) -> str:
    """Delete a file with backup to temp directory."""
    target = file_path or path or kwargs.get("file")
    if not target:
        return "Error: No file path provided."

    try:
        file_to_delete = Path(target).resolve()

        if not file_to_delete.is_file():
            return f"File does not exist: {target}"

        # Create backup in temp directory
        backup_dir = Path(tempfile.gettempdir()) / "deleted_files_backup"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / file_to_delete.name
        shutil.copy2(file_to_delete, backup_path)

        Path(file_to_delete).unlink()
        logger.info("File deleted: %s (backup: %s)", file_to_delete, backup_path)
        return "File deleted (backup saved to temp folder)"

    except Exception as e:
        logger.exception("Error deleting file: %s", e)
        return f"Error deleting file: {e}"


@tool(
    name="create_folder",
    description=(
        "Creates a new folder at the specified path. Path must be within allowed directories "
        "(Documents, Desktop, Downloads). Creates nested directories if needed. "
        "Trigger: 'create folder Projects', 'make new directory', 'mkdir notes'"
    ),
    category=ToolCategory.FILE_SYSTEM,
    parameters={"folder_name": {"type": "string", "description": "Folder name or path"}},
)
def create_folder(folder_name: str | None = None, name: str | None = None, **kwargs: Any) -> str:
    """Create a new folder."""
    target = folder_name or name or kwargs.get("path")
    if not target:
        return "Error: No folder name provided."

    try:
        folder_path = Path(target).resolve()

        # CQ-02: Sandbox the target directory
        err = _assert_in_allowed_dirs(folder_path)
        if err:
            return f"create_folder - {err}"

        if folder_path.exists():
            if folder_path.is_dir():
                return f"Folder already exists: {folder_path}"
            return f"Path exists but is not a directory: {folder_path}"

        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info("Folder created: %s", folder_path)
        return f"Folder created: {folder_path}"

    except Exception as e:
        logger.exception("Error creating folder: %s", e)
        return f"Error creating folder: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================


def get_system_tools() -> list[Tool]:
    """Get all system tools for manual registration."""
    tools = [
        open_program._tool_metadata,  # type: ignore[attr-defined]
        scan_system_applications._tool_metadata,  # type: ignore[attr-defined]
        terminate_program._tool_metadata,  # type: ignore[attr-defined]
        search_file._tool_metadata,  # type: ignore[attr-defined]
        copy_file._tool_metadata,  # type: ignore[attr-defined]
        move_file._tool_metadata,  # type: ignore[attr-defined]
        delete_file._tool_metadata,  # type: ignore[attr-defined]
        create_folder._tool_metadata,  # type: ignore[attr-defined]
    ]
    return tools
