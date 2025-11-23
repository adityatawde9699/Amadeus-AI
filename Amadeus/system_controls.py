import os
import shutil
import platform
import psutil
import subprocess
from speech_utils import recognize_speech
import time
from threading import Thread
from pathlib import Path
import tempfile
from datetime import datetime
from typing import Optional, Dict, List, Set, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# FILE READER IMPORTS
# ============================================================================

def import_pdf_reader():
    """Import PyPDF2 with proper error handling."""
    try:
        import importlib
        pdf_mod = importlib.import_module("PyPDF2")
        PdfReader = getattr(pdf_mod, "PdfReader", None)
        if PdfReader is None:
            logger.error("PyPDF2 is installed but PdfReader not found. Ensure PyPDF2>=2.x")
            return None
        return PdfReader
    except ImportError:
        logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
        return None

def import_docx_reader():
    """Import python-docx with proper error handling."""
    try:
        import importlib
        docx = importlib.import_module("docx")
        return docx
    except ImportError:
        logger.error("python-docx not installed. Install with: pip install python-docx")
        return None

def import_image_ocr():
    """Import PIL and pytesseract with proper error handling."""
    try:
        import importlib
        from PIL import Image
        pytesseract = importlib.import_module("pytesseract")
        return Image, pytesseract
    except ImportError:
        logger.error("PIL or pytesseract not installed. Install with: pip install Pillow pytesseract")
        return None, None

def import_dataframe_reader():
    """Import pandas with proper error handling."""
    try:
        import importlib
        pd = importlib.import_module("pandas")
        return pd
    except ImportError:
        logger.error("pandas not installed. Install with: pip install pandas openpyxl")
        return None

# ============================================================================
# FILE OPERATIONS
# ============================================================================

def copy_file(source_path: str | Path, destination_path: str | Path) -> bool:
    """
    Copy a file from source to destination with metadata preservation.
    
    Args:
        source_path: Path to source file
        destination_path: Path to destination file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        source_path = Path(source_path).resolve()
        destination_path = Path(destination_path).resolve()
        
        if not source_path.is_file():
            logger.error(f"Source file does not exist: {source_path}")
            return False
        
        if source_path == destination_path:
            logger.error("Source and destination paths are identical")
            return False

        destination_dir = destination_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)

        # Use atomic operation with temp file
        temp_dest = destination_dir / f".{destination_path.name}.tmp"
        shutil.copy2(source_path, temp_dest)
        temp_dest.replace(destination_path)
        
        logger.info(f"File copied: {source_path} → {destination_path}")
        print(f"✓ File copied successfully to {destination_path}")
        return True
        
    except PermissionError:
        logger.error(f"Permission denied copying file: {source_path}")
        print("✗ Permission denied. Check file permissions.")
        return False
    except IOError as e:
        logger.error(f"IO error while copying: {e}")
        print(f"✗ IO error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error copying file: {e}")
        print(f"✗ Error: {e}")
        return False

def move_file(source_path: str | Path, destination_path: str | Path) -> bool:
    """
    Move a file from source to destination.
    
    Args:
        source_path: Path to source file
        destination_path: Path to destination file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        source_path = Path(source_path).resolve()
        destination_path = Path(destination_path).resolve()
        
        if not source_path.is_file():
            logger.error(f"Source file does not exist: {source_path}")
            return False
        
        if source_path == destination_path:
            logger.error("Source and destination are the same")
            return False

        destination_dir = destination_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)

        shutil.move(str(source_path), str(destination_path))
        logger.info(f"File moved: {source_path} → {destination_path}")
        print(f"✓ File moved successfully to {destination_path}")
        return True
        
    except PermissionError:
        logger.error(f"Permission denied moving file: {source_path}")
        print("✗ Permission denied. Check file permissions.")
        return False
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        print(f"✗ Error: {e}")
        return False

def delete_file(file_path: str | Path, skip_confirmation: bool = False) -> bool:
    """
    Delete a file with optional voice confirmation.
    
    Args:
        file_path: Path to file to delete
        skip_confirmation: Skip voice confirmation if True
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        file_to_delete = Path(file_path).resolve()
        
        if not file_to_delete.is_file():
            logger.error(f"File does not exist: {file_path}")
            print(f"✗ File not found: {file_path}")
            return False
        
        if not skip_confirmation:
            print(f"Are you sure you want to permanently delete: {file_to_delete.name}?")
            confirmation = recognize_speech()
            
            if not confirmation or 'yes' not in confirmation.lower():
                print("File deletion cancelled.")
                return False
        
        # Create backup in temp directory before deletion
        backup_dir = Path(tempfile.gettempdir()) / "deleted_files_backup"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / file_to_delete.name
        shutil.copy2(file_to_delete, backup_path)
        
        os.remove(file_to_delete)
        logger.info(f"File deleted: {file_to_delete} (backup: {backup_path})")
        print(f"✓ File deleted: {file_to_delete.name}")
        return True
        
    except PermissionError:
        logger.error(f"Permission denied deleting file: {file_path}")
        print("✗ Permission denied. Check file permissions.")
        return False
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        print(f"✗ Error: {e}")
        return False

def create_folder(folder_name: str | Path) -> bool:
    """
    Create a new folder.
    
    Args:
        folder_name: Name/path of folder to create
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        folder_path = Path(folder_name).resolve()
        
        if folder_path.exists():
            if folder_path.is_dir():
                logger.warning(f"Folder already exists: {folder_path}")
                print(f"ℹ Folder already exists: {folder_path}")
                return False
            else:
                logger.error(f"Path exists but is not a directory: {folder_path}")
                print(f"✗ Path exists but is not a directory: {folder_path}")
                return False
        
        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Folder created: {folder_path}")
        print(f"✓ Folder created: {folder_path}")
        return True
        
    except PermissionError:
        logger.error(f"Permission denied creating folder: {folder_name}")
        print("✗ Permission denied. Check write permissions.")
        return False
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        print(f"✗ Error: {e}")
        return False

def create_directory(directory_path: str | Path) -> bool:
    """Create a new directory (alias for create_folder)."""
    return create_folder(directory_path)

def list_directory(directory_path: str | Path = '.') -> bool:
    """
    List contents of a directory with file sizes.
    
    Args:
        directory_path: Path to directory to list
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        directory_path = Path(directory_path).resolve()
        
        if not directory_path.exists():
            logger.error(f"Directory does not exist: {directory_path}")
            print(f"✗ Directory not found: {directory_path}")
            return False
        
        if not directory_path.is_dir():
            logger.error(f"Path is not a directory: {directory_path}")
            print(f"✗ Not a directory: {directory_path}")
            return False
        
        items = list(directory_path.iterdir())
        files = sorted([item for item in items if item.is_file()])
        dirs = sorted([item for item in items if item.is_dir()])
        
        print(f"\n📂 Directory: {directory_path}")
        print(f"   Files: {len(files)} | Subdirectories: {len(dirs)}\n")
        
        if dirs:
            print("📁 Subdirectories:")
            for d in dirs:
                print(f"   └─ {d.name}/")
        
        if files:
            print("📄 Files:")
            for f in sorted(files):
                size_kb = f.stat().st_size / 1024
                print(f"   └─ {f.name} ({size_kb:.1f} KB)")
        
        print()
        return True
        
    except PermissionError:
        logger.error(f"Permission denied listing directory: {directory_path}")
        print("✗ Permission denied.")
        return False
    except Exception as e:
        logger.error(f"Error listing directory: {e}")
        print(f"✗ Error: {e}")
        return False

# ============================================================================
# FILE SEARCH AND READ
# ============================================================================

def search_file(file_name: str, search_directory: Optional[str | Path] = None, max_results: int = 10) -> Optional[str]:
    """
    Search for files using glob patterns with timeout.
    
    Args:
        file_name: Name or pattern of file to search for
        search_directory: Directory to search in (defaults to home)
        max_results: Maximum number of results to return
        
    Returns:
        str: Path to first found file, or None if not found
    """
    try:
        search_directory = Path(search_directory or Path.home()).resolve()
        
        if not search_directory.exists():
            logger.error(f"Search directory does not exist: {search_directory}")
            print(f"✗ Directory not found: {search_directory}")
            return None
        
        logger.info(f"Searching for '{file_name}' in {search_directory}")
        print(f"🔍 Searching for '{file_name}'...")
        
        # Build search pattern
        pattern = f"**/*{file_name}*"
        found_files = []
        
        try:
            # Use rglob with timeout-like behavior
            for file_path in search_directory.rglob(file_name if "*" in file_name else f"*{file_name}*"):
                found_files.append(file_path)
                if len(found_files) >= max_results:
                    break
        except PermissionError:
            logger.warning(f"Permission denied accessing some directories")
        
        if found_files:
            logger.info(f"Found {len(found_files)} file(s)")
            print(f"✓ Found {len(found_files)} matching file(s):\n")
            for i, file_path in enumerate(found_files, 1):
                print(f"   {i}. {file_path}")
            return str(found_files[0])
        else:
            logger.warning(f"File not found: {file_name}")
            print(f"✗ No files found matching: {file_name}")
            return None
            
    except Exception as e:
        logger.error(f"Error searching for file: {e}")
        print(f"✗ Error: {e}")
        return None

def read_file(file_path: str | Path, max_chars: int = 5000) -> Optional[str]:
    """
    Read various file types and return content.
    
    Args:
        file_path: Path to file to read
        max_chars: Maximum characters to return
        
    Returns:
        str: File content or None if error
    """
    try:
        file_path = Path(file_path).resolve()
        
        if not file_path.is_file():
            logger.error(f"File does not exist: {file_path}")
            print(f"✗ File not found: {file_path}")
            return None
        
        file_extension = file_path.suffix.lower()
        content = ""
        
        logger.info(f"Reading file: {file_path}")
        print(f"📖 Reading: {file_path.name}\n")
        
        # Text files
        if file_extension == ".txt":
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(max_chars)
                if len(content) >= max_chars:
                    content += "\n\n... (content truncated)"
        
        # PDF files
        elif file_extension == ".pdf":
            PdfReader = import_pdf_reader()
            if not PdfReader:
                return None
            try:
                reader = PdfReader(file_path)
                pages_content = []
                for i in range(min(len(reader.pages), 5)):
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        pages_content.append(f"--- Page {i+1} ---\n{page_text}")
                    if sum(len(p) for p in pages_content) > max_chars:
                        break
                content = "\n\n".join(pages_content)[:max_chars]
            except Exception as e:
                logger.error(f"Error reading PDF: {e}")
                print(f"✗ Error reading PDF: {e}")
                return None
        
        # DOCX files
        elif file_extension == ".docx":
            docx = import_docx_reader()
            if not docx:
                return None
            try:
                doc = docx.Document(str(file_path))
                paras = [p.text for p in doc.paragraphs if p.text.strip()]
                content = "\n".join(paras)[:max_chars]
            except Exception as e:
                logger.error(f"Error reading DOCX: {e}")
                return None
        
        # Image files (OCR)
        elif file_extension in [".png", ".jpg", ".jpeg", ".bmp", ".gif"]:
            Image, pytesseract = import_image_ocr()
            if not Image or not pytesseract:
                return None
            try:
                print("⏳ Performing OCR on image...")
                img = Image.open(file_path)
                content = pytesseract.image_to_string(img)
                if not content.strip():
                    content = "(No text found in image)"
            except Exception as e:
                logger.error(f"Error reading image: {e}")
                return None
        
        # Data files (CSV/Excel)
        elif file_extension in [".csv", ".xlsx", ".xls"]:
            pd = import_dataframe_reader()
            if not pd:
                return None
            try:
                df = pd.read_csv(file_path) if file_extension == ".csv" else pd.read_excel(file_path)
                if len(df) > 20:
                    content = df.head(10).to_string()
                    content += f"\n\n(Showing 10 of {len(df)} rows)"
                else:
                    content = df.to_string()
            except Exception as e:
                logger.error(f"Error reading data file: {e}")
                return None
        
        else:
            logger.error(f"Unsupported file type: {file_extension}")
            print(f"✗ Unsupported file format: {file_extension}")
            return None
        
        # Display content
        print("─" * 60)
        display_length = min(len(content), 1500)
        print(content[:display_length])
        if display_length < len(content):
            print(f"\n... (content truncated - {len(content) - display_length} chars hidden)")
        print("─" * 60 + "\n")
        
        return content
        
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        print(f"✗ Error: {e}")
        return None

# ============================================================================
# APPLICATION MANAGEMENT
# ============================================================================

windows_apps = {
    "brave": "brave.exe",
    "calculator": "calc.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "telegram": "Telegram.exe",
    "vlc": "vlc.exe",
    "notepad": "notepad.exe",
    "file explorer": "explorer.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "photoshop": "Photoshop.exe",
    "spotify": "Spotify.exe",
    "slack": "slack.exe",
    "zoom": "Zoom.exe",
    "firefox": "firefox.exe",
    "opera": "opera.exe",
    "teams": "Teams.exe",
    "onenote": "onenote.exe",
    "outlook": "outlook.exe",
    "skype": "skype.exe",
    "steam": "steam.exe",
    "discord": "Discord.exe",
    "adobe reader": "AcroRd32.exe",
    "illustrator": "Illustrator.exe",
    "blender": "blender.exe",
    "gimp": "gimp-2.10.exe",
    "audacity": "audacity.exe",
    "pycharm": "pycharm64.exe",
    "eclipse": "eclipse.exe",
    "virtualbox": "VirtualBox.exe",
    "vmware": "vmware.exe",
    "sublime text": "sublime_text.exe",
    "atom": "atom.exe",
    "brackets": "Brackets.exe",
    "postman": "Postman.exe",
    "git": "git.exe",
    "docker": "Docker Desktop.exe"
}

mac_apps = {
    "calculator": "Calculator",
    "chrome": "Google Chrome",
    "safari": "Safari",
    "telegram": "Telegram",
    "vlc": "VLC",
    "textedit": "TextEdit",
    "finder": "Finder",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "photoshop": "Adobe Photoshop",
    "spotify": "Spotify",
    "slack": "Slack",
    "zoom": "zoom.us",
    "firefox": "Firefox",
    "opera": "Opera",
    "teams": "Microsoft Teams",
    "onenote": "Microsoft OneNote",
    "outlook": "Microsoft Outlook",
    "skype": "Skype",
    "steam": "Steam",
    "discord": "Discord",
    "adobe reader": "Adobe Acrobat Reader DC",
    "illustrator": "Adobe Illustrator",
    "blender": "Blender",
    "gimp": "GIMP",
    "audacity": "Audacity",
    "pycharm": "PyCharm",
    "eclipse": "Eclipse",
    "virtualbox": "VirtualBox",
    "vmware": "VMware Fusion",
    "sublime text": "Sublime Text",
    "atom": "Atom",
    "brackets": "Brackets",
    "postman": "Postman",
    "terminal": "Terminal",
    "docker": "Docker"
}

linux_apps = {
    "calculator": "gnome-calculator",
    "chrome": "google-chrome",
    "firefox": "firefox",
    "telegram": "telegram-desktop",
    "vlc": "vlc",
    "gedit": "gedit",
    "file explorer": "nautilus",
    "libreoffice writer": "libreoffice --writer",
    "libreoffice calc": "libreoffice --calc",
    "libreoffice impress": "libreoffice --impress",
    "gimp": "gimp",
    "spotify": "spotify",
    "slack": "slack",
    "zoom": "zoom",
    "opera": "opera",
    "skype": "skype",
    "steam": "steam",
    "discord": "discord",
    "blender": "blender",
    "audacity": "audacity",
    "pycharm": "pycharm",
    "eclipse": "eclipse",
    "virtualbox": "virtualbox",
    "sublime text": "subl",
    "atom": "atom",
    "postman": "postman",
    "terminal": "gnome-terminal",
    "docker": "docker"
}

def get_app_name(command: str) -> Optional[str]:
    """
    Get normalized app executable name based on platform and user command.
    
    Args:
        command: User-friendly app name or partial name
        
    Returns:
        str: App executable name or None if not found
    """
    try:
        app_dict = {
            "Windows": windows_apps,
            "Darwin": mac_apps,
            "Linux": linux_apps
        }.get(platform.system())
        
        if not app_dict:
            logger.error(f"Unsupported OS: {platform.system()}")
            print("✗ Unsupported operating system.")
            return None
        
        command_lower = command.lower()
        
        # Exact match
        if command_lower in app_dict:
            return app_dict[command_lower]
        
        # Partial match
        for key, value in app_dict.items():
            if key in command_lower:
                return value
        
        logger.warning(f"Application not found: {command}")
        print(f"✗ Application '{command}' not found in known applications.")
        return None
        
    except Exception as e:
        logger.error(f"Error getting app name: {e}")
        return None

def find_app_process(app_name: str) -> Optional[str]:
    """
    Find running process matching application name with fuzzy matching.
    
    Args:
        app_name: Application name to find
        
    Returns:
        str: Process name if found, None otherwise
    """
    try:
        app_lower = app_name.lower().replace(".exe", "").strip()
        
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                proc_name = proc.info['name'].lower().replace(".exe", "").strip()
                
                # Various matching strategies
                if (app_lower == proc_name or
                    app_lower in proc_name or
                    proc_name in app_lower or
                    any(word in proc_name for word in app_lower.split())):
                    return proc.info['name']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return None
    except Exception as e:
        logger.error(f"Error finding app process: {e}")
        return None

def open_program(app_name: str, timeout: int = 15) -> bool:
    """
    Open an application with verification.
    
    Args:
        app_name: Name of application to open
        timeout: Timeout to wait for app launch (seconds)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        app_exec = get_app_name(app_name)
        if not app_exec:
            print(f"✗ Cannot find application: {app_name}")
            return False
        
        logger.info(f"Opening application: {app_name} ({app_exec})")
        print(f"🚀 Opening {app_name}...")
        
        # Get process list before
        try:
            processes_before = {p.info['name'] for p in psutil.process_iter(['name'])}
        except:
            processes_before = set()
        
        # Launch based on platform
        try:
            if platform.system() == "Windows":
                try:
                    os.startfile(app_exec)
                except FileNotFoundError:
                    subprocess.Popen(app_exec, shell=True)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", "-a", app_exec])
            elif platform.system() == "Linux":
                subprocess.Popen(app_exec, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                print("✗ Unsupported operating system.")
                return False
        except Exception as e:
            logger.error(f"Error launching app: {e}")
            print(f"✗ Error launching: {e}")
            return False
        
        # Wait and verify
        for elapsed in range(timeout):
            time.sleep(1)
            
            try:
                processes_after = {p.info['name'] for p in psutil.process_iter(['name'])}
                if processes_after - processes_before:
                    logger.info(f"Application launched successfully: {app_name}")
                    print(f"✓ {app_name} launched successfully!")
                    return True
            except:
                pass
            
            if elapsed % 3 == 0 and elapsed > 0:
                print(f"⏳ Waiting for {app_name} ({timeout - elapsed}s)...")
        
        logger.warning(f"App may not have launched: {app_name}")
        print(f"⚠ {app_name} may not have launched correctly.")
        return True  # Return True anyway as app might be starting
        
    except Exception as e:
        logger.error(f"Error opening program: {e}")
        print(f"✗ Error: {e}")
        return False

def terminate_program(process_name: str) -> int:
    """
    Terminate all processes matching the name.
    
    Args:
        process_name: Name of process to terminate
        
    Returns:
        int: Number of processes terminated
    """
    try:
        count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if process_name.lower() in proc.info['name'].lower():
                    proc_obj = psutil.Process(proc.info['pid'])
                    proc_obj.terminate()
                    count += 1
                    logger.info(f"Terminated process: {proc.info['name']} (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if count > 0:
            print(f"✓ Terminated {count} process(es) matching '{process_name}'")
        else:
            print(f"✗ No processes found matching '{process_name}'")
        
        return count
        
    except Exception as e:
        logger.error(f"Error terminating program: {e}")
        print(f"✗ Error: {e}")
        return 0

def manage_process(process: Dict) -> str:
    """
    Interactive process management menu.
    
    Args:
        process: Process info dictionary with pid, name, etc.
        
    Returns:
        str: Result message
    """
    try:
        print(f"\n{'─' * 50}")
        print(f"Process: {process['name']} (PID: {process['pid']})")
        print(f"{'─' * 50}")
        print("1. View details")
        print("2. Terminate process")
        print("3. Cancel")
        print(f"{'─' * 50}\n")
        
        choice = recognize_speech()
        
        if choice:
            choice_lower = choice.lower()
            
            if "details" in choice_lower or "1" in choice:
                try:
                    proc = psutil.Process(process['pid'])
                    cpu = proc.cpu_percent(interval=0.1)
                    mem = proc.memory_percent()
                    created = datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S')
                    
                    details = f"""
Process Details:
  Name:      {process['name']}
  PID:       {process['pid']}
  CPU:       {cpu:.1f}%
  Memory:    {mem:.1f}%
  Status:    {proc.status()}
  Created:   {created}
"""
                    print(details)
                    return "Process details displayed."
                except Exception as e:
                    return f"Error getting details: {e}"
            
            elif "terminate" in choice_lower or "kill" in choice_lower or "2" in choice:
                try:
                    psutil.Process(process['pid']).terminate()
                    logger.info(f"Terminated process: {process['name']}")
                    return f"✓ Process {process['name']} terminated."
                except Exception as e:
                    return f"Error terminating: {e}"
        
        return "No action taken."
        
    except Exception as e:
        logger.error(f"Error managing process: {e}")
        return f"Error: {str(e)}"