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


# =============================================================================
# APPLICATION MAPPINGS
# =============================================================================

WINDOWS_APPS = {
    "brave": "brave.exe", "calculator": "calc.exe", "chrome": "chrome.exe",
    "edge": "msedge.exe", "telegram": "Telegram.exe", "vlc": "vlc.exe",
    "notepad": "notepad.exe", "file explorer": "explorer.exe", "word": "winword.exe",
    "excel": "excel.exe", "powerpoint": "powerpnt.exe", "photoshop": "Photoshop.exe",
    "spotify": "Spotify.exe", "slack": "slack.exe", "zoom": "Zoom.exe",
    "firefox": "firefox.exe", "opera": "opera.exe", "teams": "Teams.exe",
    "onenote": "onenote.exe", "outlook": "outlook.exe", "skype": "skype.exe",
    "steam": "steam.exe", "discord": "Discord.exe", "vscode": "Code.exe",
    "visual studio code": "Code.exe", "code": "Code.exe",
    "pycharm": "pycharm64.exe", "sublime text": "sublime_text.exe",
    "postman": "Postman.exe", "docker": "Docker Desktop.exe",
}

MAC_APPS = {
    "calculator": "Calculator", "chrome": "Google Chrome", "safari": "Safari",
    "telegram": "Telegram", "vlc": "VLC", "textedit": "TextEdit",
    "finder": "Finder", "word": "Microsoft Word", "excel": "Microsoft Excel",
    "spotify": "Spotify", "slack": "Slack", "zoom": "zoom.us",
    "firefox": "Firefox", "discord": "Discord", "vscode": "Visual Studio Code",
    "terminal": "Terminal", "docker": "Docker",
}

LINUX_APPS = {
    "calculator": "gnome-calculator", "chrome": "google-chrome",
    "firefox": "firefox", "telegram": "telegram-desktop", "vlc": "vlc",
    "gedit": "gedit", "file explorer": "nautilus", "spotify": "spotify",
    "slack": "slack", "discord": "discord", "vscode": "code",
    "terminal": "gnome-terminal", "docker": "docker",
}


def _get_app_executable(app_name: str) -> str | None:
    """Get app executable name based on platform."""
    app_dict = {
        "Windows": WINDOWS_APPS,
        "Darwin": MAC_APPS,
        "Linux": LINUX_APPS,
    }.get(platform.system(), {})
    
    app_lower = app_name.lower()
    
    # Exact match
    if app_lower in app_dict:
        return app_dict[app_lower]
    
    # Partial match
    for key, value in app_dict.items():
        if key in app_lower or app_lower in key:
            return value
    
    # Return as-is for unknown apps
    return app_name


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
    """Open an application with verification."""
    target_app = app_name or program_name or kwargs.get("name")
    if not target_app:
        return "Error: No application name provided."
    
    app_exec = _get_app_executable(target_app)
    if not app_exec:
        return f"Could not find application: {target_app}"
    
    logger.info(f"Opening application: {target_app} ({app_exec})")
    
    try:
        if platform.system() == "Windows":
            try:
                os.startfile(app_exec)
            except FileNotFoundError:
                subprocess.Popen(app_exec, shell=True)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", app_exec])
        elif platform.system() == "Linux":
            subprocess.Popen(app_exec, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return f"Unsupported operating system: {platform.system()}"
        
        return f"Opening {target_app}..."
        
    except Exception as e:
        logger.error(f"Error launching app {target_app}: {e}")
        return f"Failed to open {target_app}: {e}"


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
    """Search for files using glob patterns."""
    target = file_name or name or kwargs.get("query")
    if not target:
        return "Error: No file name provided."
    
    try:
        search_dir = Path.home()
        logger.info(f"Searching for '{target}' in {search_dir}")
        
        found_files = []
        pattern = f"*{target}*" if "*" not in target else target
        
        try:
            for file_path in search_dir.rglob(pattern):
                found_files.append(file_path)
                if len(found_files) >= 10:
                    break
        except PermissionError:
            pass
        
        if found_files:
            result = f"Found {len(found_files)} file(s):\n"
            for f in found_files[:5]:
                result += f"  - {f}\n"
            if len(found_files) > 5:
                result += f"  ... and {len(found_files) - 5} more"
            return result
        
        return f"No files found matching '{target}'"
        
    except Exception as e:
        logger.error(f"Error searching for '{target}': {e}")
        return f"Error searching for file: {e}"


@tool(
    name="read_file",
    description="Open and display file contents (.txt/.pdf/.json). Trigger: 'read file', 'show content'",
    category=ToolCategory.SYSTEM,
    parameters={"file_path": {"type": "string", "description": "Path to file to read"}}
)
def read_file(file_path: str | None = None, path: str | None = None, **kwargs: Any) -> str:
    """Read various file types and return content."""
    target = file_path or path or kwargs.get("file")
    if not target:
        return "Error: No file path provided."
    
    try:
        file_path_obj = Path(target).resolve()
        
        if not file_path_obj.is_file():
            return f"File does not exist: {target}"
        
        extension = file_path_obj.suffix.lower()
        max_chars = 5000
        
        if extension == ".txt":
            with open(file_path_obj, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(max_chars)
                if len(content) >= max_chars:
                    content += "\n\n... (content truncated)"
                return content
        
        elif extension == ".json":
            import json
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return json.dumps(data, indent=2)[:max_chars]
        
        elif extension == ".pdf":
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(file_path_obj)
                content = []
                for i, page in enumerate(reader.pages[:5]):
                    text = page.extract_text()
                    if text:
                        content.append(f"--- Page {i+1} ---\n{text}")
                return "\n\n".join(content)[:max_chars]
            except ImportError:
                return "PyPDF2 not installed. Install with: pip install PyPDF2"
        
        else:
            return f"Unsupported file type: {extension}"
            
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return f"Error reading file: {e}"


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


@tool(
    name="list_directory",
    description="List files in folder. Trigger: 'ls', 'dir', 'what's in folder'",
    category=ToolCategory.SYSTEM,
    parameters={"directory_path": {"type": "string", "description": "Directory path to list"}}
)
def list_directory(directory_path: str | None = None, path: str | None = None, **kwargs: Any) -> str:
    """List contents of a directory."""
    target = directory_path or path or kwargs.get("dir") or "."
    
    try:
        dir_path = Path(target).resolve()
        
        if not dir_path.exists():
            return f"Directory does not exist: {target}"
        
        if not dir_path.is_dir():
            return f"Path is not a directory: {target}"
        
        items = list(dir_path.iterdir())
        files = sorted([i for i in items if i.is_file()])
        dirs = sorted([i for i in items if i.is_dir()])
        
        result = f"Contents of {dir_path}:\n\n"
        
        if dirs:
            result += "📁 Directories:\n"
            for d in dirs[:10]:
                result += f"  {d.name}/\n"
            if len(dirs) > 10:
                result += f"  ... and {len(dirs) - 10} more\n"
        
        if files:
            result += "\n📄 Files:\n"
            for f in files[:10]:
                size_kb = f.stat().st_size / 1024
                result += f"  {f.name} ({size_kb:.1f} KB)\n"
            if len(files) > 10:
                result += f"  ... and {len(files) - 10} more\n"
        
        if not items:
            result += "(empty directory)"
        
        return result
        
    except Exception as e:
        logger.error(f"Error listing directory: {e}")
        return f"Error listing directory: {e}"


# =============================================================================
# TOOL COLLECTION
# =============================================================================

def get_system_tools() -> list[Tool]:
    """Get all system tools for manual registration."""
    tools = []
    for name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools
