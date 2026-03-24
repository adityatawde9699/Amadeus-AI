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
import time
from pathlib import Path
from typing import Any

import psutil

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

from src.infra.system.app_registry import AppRegistry

# Initialize global registry locally for tools since tool execution happens statically
# In a fully DI environment, this might be injected into ToolConfig
app_registry = AppRegistry()


# =============================================================================
# APPLICATION TOOLS
# =============================================================================

@tool(
    name="open_program",
    description="Launch desktop apps (Chrome/VSCode/Word). Trigger: 'open app', 'start ___'",
    category=ToolCategory.SYSTEM,
    parameters={"app_name": {"type": "string", "description": "Application name to open"}}
)
def open_program(app_name: str | None = None, program_name: str | None = None, **kwargs: Any) -> str:
    """Open an application using the dynamic AppRegistry with fuzzy matching."""
    target_app = app_name or program_name or kwargs.get("name")
    if not target_app:
        return "Error: No application name provided."
    
    app_exec = app_registry.get_executable(target_app)
    if not app_exec:
        return f"Cannot find '{target_app}' on this system. You may need to trigger a system scan using `scan_system_applications`."
    
    logger.info(f"Opening application: {target_app} ({app_exec})")
    
    try:
        if platform.system() == "Windows":
            try:
                os.startfile(app_exec)  # noqa: S606
            except (FileNotFoundError, OSError):
                subprocess.Popen([app_exec], shell=False)  # noqa: S603
        elif platform.system() == "Darwin":
            # On Mac, app_exec from registry is absolute path to .app bundle
            subprocess.Popen(["open", app_exec])  # noqa: S603
        elif platform.system() == "Linux":
            # On Linux, app_exec is often the stem of the .desktop file
            subprocess.Popen(["gtk-launch", app_exec], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        else:
            return f"Unsupported operating system: {platform.system()}"
        
        return f"Opening {target_app}..."
        
    except Exception as e:
        logger.error(f"Error launching app {target_app}: {e}")
        return f"Failed to open {target_app}: {e}"

@tool(
    name="scan_system_applications",
    description="Forces a deep scan of the local OS to find newly installed applications and rebuild the app cache. Trigger: 'scan apps', 'find new apps'",
    category=ToolCategory.SYSTEM,
    parameters={}
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
    description="Kill/stop app. Trigger: 'close app', 'kill process'",
    category=ToolCategory.SYSTEM,
    parameters={"process_name": {"type": "string", "description": "Process name to terminate"}},
    requires_confirmation=True,
)
def terminate_program(process_name: str | None = None, app_name: str | None = None, **kwargs: Any) -> str:
    """Terminate all processes matching the name."""
    target = process_name or app_name or kwargs.get("name")
    if not target:
        return "Error: No process name provided."
    
    try:
        count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if target.lower() in proc.info['name'].lower():
                    psutil.Process(proc.info['pid']).terminate()
                    count += 1
                    logger.info(f"Terminated: {proc.info['name']} (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if count > 0:
            return f"Terminated {count} process(es) matching '{target}'"
        return f"No processes found matching '{target}'"
        
    except Exception as e:
        logger.error(f"Error terminating '{target}': {e}")
        return f"Error terminating process: {e}"


# =============================================================================
# FILE OPERATION TOOLS
# =============================================================================

@tool(
    name="search_file",
    description="Find files by name (returns path). Trigger: 'find file', 'where is file', 'locate ___'",
    category=ToolCategory.SYSTEM,
    parameters={"file_name": {"type": "string", "description": "File name or pattern to search"}}
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
            f"on this system. Check SEARCH_ALLOWED_DIRS in your .env file."
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
    description="Duplicate file. Trigger: 'copy file'",
    category=ToolCategory.SYSTEM,
    parameters={
        "source_path": {"type": "string", "description": "Source file path"},
        "destination_path": {"type": "string", "description": "Destination file path"}
    }
)
def copy_file(source_path: str | None = None, destination_path: str | None = None, **kwargs: Any) -> str:
    """Copy a file from source to destination."""
    src = source_path or kwargs.get("source") or kwargs.get("src")
    dst = destination_path or kwargs.get("destination") or kwargs.get("dest")
    
    if not src or not dst:
        return "Error: Source and destination paths required."
    
    try:
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()
        
        if not src_path.is_file():
            return f"Source file does not exist: {src}"
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        
        logger.info(f"File copied: {src_path} → {dst_path}")
        return f"File copied to {dst_path}"
        
    except Exception as e:
        logger.error(f"Error copying file: {e}")
        return f"Error copying file: {e}"


@tool(
    name="move_file",
    description="Move file. Trigger: 'move file'",
    category=ToolCategory.SYSTEM,
    parameters={
        "source_path": {"type": "string", "description": "Source file path"},
        "destination_path": {"type": "string", "description": "Destination file path"}
    }
)
def move_file(source_path: str | None = None, destination_path: str | None = None, **kwargs: Any) -> str:
    """Move a file from source to destination."""
    src = source_path or kwargs.get("source")
    dst = destination_path or kwargs.get("destination")
    
    if not src or not dst:
        return "Error: Source and destination paths required."
    
    try:
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()
        
        if not src_path.is_file():
            return f"Source file does not exist: {src}"
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        
        logger.info(f"File moved: {src_path} → {dst_path}")
        return f"File moved to {dst_path}"
        
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        return f"Error moving file: {e}"


@tool(
    name="delete_file",
    description="Delete file permanently. Trigger: 'delete file'",
    category=ToolCategory.SYSTEM,
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
        
        os.remove(file_to_delete)
        logger.info(f"File deleted: {file_to_delete} (backup: {backup_path})")
        return f"File deleted (backup saved to temp folder)"
        
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return f"Error deleting file: {e}"


@tool(
    name="create_folder",
    description="Create folder. Trigger: 'make folder'",
    category=ToolCategory.SYSTEM,
    parameters={"folder_name": {"type": "string", "description": "Folder name or path"}}
)
def create_folder(folder_name: str | None = None, name: str | None = None, **kwargs: Any) -> str:
    """Create a new folder."""
    target = folder_name or name or kwargs.get("path")
    if not target:
        return "Error: No folder name provided."
    
    try:
        folder_path = Path(target).resolve()
        
        if folder_path.exists():
            if folder_path.is_dir():
                return f"Folder already exists: {folder_path}"
            return f"Path exists but is not a directory: {folder_path}"
        
        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Folder created: {folder_path}")
        return f"Folder created: {folder_path}"
        
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        return f"Error creating folder: {e}"





# =============================================================================
# TOOL COLLECTION
# =============================================================================

from src.infra.tools.office_tools import get_office_tools
from src.infra.tools.slack_tools import get_slack_tools

def get_system_tools() -> list[Tool]:
    """Get all system tools for manual registration."""
    tools = []
    # Collect tools from this module (system_tools.py)
    for name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    
    # Collect from office and slack sub-modules
    tools.extend(get_office_tools())
    tools.extend(get_slack_tools())
    
    return tools

