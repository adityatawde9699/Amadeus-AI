import os
import shutil
import platform
import psutil
import subprocess
from speech_utils import speak, recognize_speech
import time
from threading import Thread
from pathlib import Path  # For better path handling
import tempfile  # For creating temporary directories
from datetime import datetime

# File readers - import only when needed
def import_pdf_reader():
    try:
        import importlib
        pdf_mod = importlib.import_module("PyPDF2")
        PdfReader = getattr(pdf_mod, "PdfReader", None)
        if PdfReader is None:
            speak("PyPDF2 is installed but PdfReader could not be found. Please ensure PyPDF2>=2.x is installed.")
            return None
        return PdfReader
    except Exception:
        speak("PyPDF2 library not found. Please install it to read PDF files.")
        return None

def import_docx_reader():
    try:
        import importlib
        docx = importlib.import_module("docx")
        return docx
    except Exception:
        speak("python-docx library not found. Please install it to read DOCX files.")
        return None

def import_image_ocr():
    try:
        import importlib
        Image = importlib.import_module("PIL.Image")
        pytesseract = importlib.import_module("pytesseract")
        return Image, pytesseract
    except Exception:
        speak("PIL (Pillow) or pytesseract libraries not found. Please install them for image OCR.")
        return None, None

def import_dataframe_reader():
    try:
        import importlib
        pd = importlib.import_module("pandas")
        return pd
    except ImportError:
        speak("pandas library not found. Please install it to read CSV or Excel files.")
        return None
    except Exception as e:
        speak(f"An unexpected error occurred while importing pandas: {e}")
        return None

def copy_file(source_path, destination_path):
    """Copies a file from source to destination."""
    try:
        source_path = Path(source_path).resolve()
        destination_path = Path(destination_path).resolve()
        
        if not source_path.is_file():
            speak(f"Source file {source_path} does not exist.")
            return False

        # Ensure the destination directory exists
        destination_dir = destination_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(source_path, destination_path)  # copy2 preserves metadata
        speak(f"File copied from {source_path} to {destination_path}.")
        print(f"File copied from {source_path} to {destination_path}.")
        return True
    except Exception as e:
        speak(f"An error occurred while copying the file: {e}")
        print(f"An error occurred while copying the file: {e}")
        return False
    
def create_folder(folder_name):
    """Creates a new folder."""
    try:
        folder_path = Path(folder_name).resolve()
        if folder_path.exists():
            speak(f"Folder {folder_path} already exists.")
            return False
            
        folder_path.mkdir(parents=True, exist_ok=True)
        speak(f"Created folder: {folder_path}")
        return True
    
    except Exception as e:
        speak(f"An error occurred while creating the folder: {e}")
        print(f"An error occurred while creating the folder: {e}")
        return False


def move_file(source_path, destination_path):
    """Moves a file from source to destination."""
    try:
        source_path = Path(source_path).resolve()
        destination_path = Path(destination_path).resolve()
        
        if not source_path.is_file():
            speak(f"Source file {source_path} does not exist.")
            return False

        # Ensure the destination directory exists
        destination_dir = destination_path.parent
        destination_dir.mkdir(parents=True, exist_ok=True)

        shutil.move(source_path, destination_path)
        speak(f"File moved from {source_path} to {destination_path}.")
        print(f"File moved from {source_path} to {destination_path}.")
        return True
    except Exception as e:
        speak(f"An error occurred while moving the file: {e}")
        print(f"An error occurred while moving the file: {e}")
        return False

# Application mapping - now with platform-specific dictionaries
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

def get_app_name(command):
    """Normalize user-friendly names to app executable names based on platform."""
    try:
        # Determine which app dictionary to use based on platform
        if platform.system() == "Windows":
            app_dict = windows_apps
        elif platform.system() == "Darwin":  # macOS
            app_dict = mac_apps
        elif platform.system() == "Linux":
            app_dict = linux_apps
        else:
            speak("Unsupported operating system.")
            return None
        
        # Check if any app name is in the command
        for key in app_dict.keys():
            if key.lower() in command.lower():
                return app_dict[key]
        
        # If not found but command matches an executable directly, return it
        if command in app_dict.values():
            return command
            
        speak(f"Application '{command}' not found in known applications.")
        return None
    except Exception as e:
        speak(f"An error occurred while getting the application name: {e}")
        print(f"An error occurred while getting the application name: {e}")
        return None
    
def open_program(app_name):
    """Opens an application with better verification that it actually launched."""
    try:
        app_exec = get_app_name(app_name)  # This function needs to be defined elsewhere
        if not app_exec:
            speak(f"Sorry, I cannot find the application {app_name}")
            return False
        
        # Get process list before opening
        processes_before = set(p.info['name'] for p in psutil.process_iter(['name']))
       
        # Open based on platform
        if platform.system() == "Windows":
            try:
                # First try with startfile which is better for Windows
                os.startfile(app_exec)
            except:
                # Fall back to subprocess if startfile fails
                subprocess.Popen(app_exec, shell=True)
        elif platform.system() == "Linux":
            subprocess.Popen(app_exec, shell=True)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", "-a", app_exec])
        else:
            speak("Unsupported operating system.")
            return False
           
        speak(f"Attempting to open {app_name}...")
       
        # Wait and check for app to actually start
        max_wait = 10  # seconds
        for i in range(max_wait):
            time.sleep(1)
           
            # Check processes after attempting to open
            processes_after = set(p.info['name'] for p in psutil.process_iter(['name']))
            new_processes = processes_after - processes_before
           
            # Check if any new process appeared
            if new_processes:
                speak(f"{app_name} has been launched successfully.")
                return True
           
            # Continue waiting
            if i % 3 == 0 and i > 0:
                speak(f"Still waiting for {app_name} to start...")
       
        # If we get here, the app probably didn't start
        speak(f"Warning: {app_name} might not have launched correctly. No new matching process was detected.")
        return False
    except Exception as e:
        speak(f"Could not open {app_name}: {e}")
        print(f"Could not open {app_name}: {e}")
        return False
# Helper function to match app names more flexibly
def find_app_process(app_name):
    """Find a running process that might match the application name using fuzzy matching."""
    try:
        app_lower = app_name.lower()
        # Remove common extensions and words for better matching
        app_clean = app_lower.replace(".exe", "").replace("microsoft", "").replace("google", "").strip()
        
        for proc in psutil.process_iter(['name']):
            proc_lower = proc.info['name'].lower()
            proc_clean = proc_lower.replace(".exe", "").replace("microsoft", "").replace("google", "").strip()
            
            # Check for matches in various ways
            if (app_clean == proc_clean or
                app_clean in proc_clean or
                proc_clean in app_clean or
                # Check for acronyms (e.g., "Microsoft Word" -> "word")
                any(word in proc_clean for word in app_clean.split())):
                return proc.info['name']
                
        return None
    except:
        return None

def terminate_program(process_name):
    """
    Terminate a program by name.
    
    Args:
        process_name (str): Name of the process to terminate
        
    Returns:
        int: Number of processes terminated
    """
    try:
        import psutil
        
        count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            if process_name.lower() in proc.info['name'].lower():
                try:
                    psutil.Process(proc.info['pid']).terminate()
                    count += 1
                except:
                    pass
        
        return count
    except Exception as e:
        print(f"Error terminating program: {e}")
        return 0

def manage_process(process):
    """
    Provide options to manage a selected process.
    
    Args:
        process (dict): Process information dictionary
        
    Returns:
        str: Result of the operation
    """
    try:
        import psutil
        
        print(f"\nProcess: {process['name']} (PID: {process['pid']})")
        print("1. View details")
        print("2. Terminate process")
        print("3. Change priority")
        print("4. Cancel")
        
        print("What would you like to do with this process?")
        choice = recognize_speech()
        
        if choice:
            if "details" in choice.lower() or "1" in choice:
                proc = psutil.Process(process['pid'])
                details = f"""
Process Details:
Name:     {process['name']}
PID:      {process['pid']}
CPU:      {process['cpu_percent']}%
Memory:   {process['memory_percent']}%
Status:   {process['status']}
Created:  {datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S')}
"""
                print(details)
                return "Process details displayed."
                
            elif "terminate" in choice.lower() or "kill" in choice.lower() or "2" in choice:
                psutil.Process(process['pid']).terminate()
                return f"Process {process['name']} terminated."
                
            elif "priority" in choice.lower() or "3" in choice:
                print("Changing priority requires administrative privileges.")
                return "Changing priority requires elevated permissions."
        
        return "No action taken."
        
    except Exception as e:
        print(f"Error managing process: {e}")
        return f"Error managing process: {str(e)}"


def search_file(file_name, search_directory=None):
    """Searches for a file using a faster glob pattern."""
    try:
        if search_directory is None:
            search_directory = Path.home()
        else:
            search_directory = Path(search_directory)

        if not search_directory.exists():
            speak(f"Search directory {search_directory} does not exist.")
            return None

        speak(f"Searching for {file_name} in {search_directory}. This may be quick.")
        
        # Use rglob for recursive globbing - much faster than os.walk for simple patterns
        # The pattern '**/*' searches all subdirectories
        pattern = f"**/*{file_name}*"
        found_files = list(search_directory.rglob(pattern))

        if found_files:
            speak(f"Found {len(found_files)} matching file(s). The first one is at {found_files[0]}")
            for file_path in found_files[:5]: # Print first 5
                print(f"Found: {file_path}")
            return str(found_files[0])
        else:
            speak(f"Sorry, I could not find any file named {file_name}.")
            return None
    except Exception as e:
        speak(f"An error occurred during the file search: {e}")
        return None

def read_file(file_path, max_chars=5000):
    """Reads and returns the content of various file types as a string (also speaks briefly)."""
    try:
        file_path = Path(file_path)
        if not file_path.is_file():
            speak(f"{file_path} does not exist.")
            return None

        file_extension = file_path.suffix.lower()
        content = ""

        # Handle different file types
        if file_extension == ".txt":
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read(max_chars)
                if len(content) >= max_chars:
                    content += "... (content truncated due to large file size)"
        
        elif file_extension == ".pdf":
            PdfReader = import_pdf_reader()
            if not PdfReader:
                return None
            reader = PdfReader(file_path)
            pages_content = []
            for i in range(min(len(reader.pages), 5)):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    pages_content.append(f"--- Page {i+1} ---\n{page_text}")
                if sum(len(p) for p in pages_content) > max_chars:
                    pages_content[-1] = pages_content[-1][:max_chars - sum(len(p) for p in pages_content[:-1])]
                    pages_content[-1] += "... (content truncated due to large file size)"
                    break
            content = "\n\n".join(pages_content)

        elif file_extension == ".docx":
            docx = import_docx_reader()
            if not docx:
                return None
            doc = docx.Document(str(file_path))
            paras = [para.text for para in doc.paragraphs if para.text.strip()]
            total_len = 0
            truncated_paras = []
            for para in paras:
                if total_len + len(para) <= max_chars:
                    truncated_paras.append(para)
                    total_len += len(para) + 1
                else:
                    available_chars = max_chars - total_len
                    if available_chars > 0:
                        truncated_paras.append(para[:available_chars] + "... (content truncated)")
                    break
            content = "\n".join(truncated_paras)

        elif file_extension in [".png", ".jpg", ".jpeg"]:
            Image, pytesseract = import_image_ocr()
            if not Image or not pytesseract:
                return None
            speak("Analyzing image content. This may take a moment.")
            img = Image.open(file_path)
            content = pytesseract.image_to_string(img)
            if not content.strip():
                content = "No text could be extracted from this image."

        elif file_extension in [".csv", ".xlsx"]:
            pd = import_dataframe_reader()
            if not pd:
                return None
            df = pd.read_csv(file_path) if file_extension == ".csv" else pd.read_excel(file_path)
            if len(df) > 20:
                speak(f"This file contains {len(df)} rows. Showing first 10 rows.")
                content = df.head(10).to_string()
                content += f"\n\n(Showing 10 of {len(df)} rows)"
            else:
                content = df.to_string()

        else:
            speak(f"Unsupported file format: {file_extension}")
            return None

        print("\n--- File Content ---")
        print(content)
        print("--- End of Content ---\n")

        # Speak a limited preview
        speak_limit = min(len(content), 1000)
        speak(content[:speak_limit])
        if speak_limit < len(content):
            speak("Content was truncated for speech. The full content is shown in the console.")
        
        return content

    except Exception as e:
        speak(f"An error occurred while reading the file: {e}")
        print(f"An error occurred while reading the file: {e}")
        return None
    
def delete_file(file_path, skip_confirmation=False):
    """Deletes a file after user voice confirmation."""
    try:
        file_to_delete = Path(file_path).resolve()
        if not file_to_delete.is_file():
            speak(f"The file {file_path} does not exist.")
            return False
            
        if not skip_confirmation:
            speak(f"Are you sure you want to permanently delete the file: {file_to_delete.name}? Please say yes to confirm.")
            confirmation = recognize_speech() # Get voice confirmation
            
            if not confirmation or 'yes' not in confirmation.lower():
                speak("File deletion cancelled.")
                return False
                
        # Perform the deletion
        os.remove(file_to_delete)
        speak(f"The file {file_to_delete.name} has been permanently deleted.")
        return True
        
    except Exception as e:
        speak(f"An error occurred while deleting the file: {e}")
        return False

def create_directory(directory_path):
    """Creates a new directory."""
    try:
        directory_path = Path(directory_path)
        if directory_path.exists():
            speak(f"Directory {directory_path} already exists.")
            return False
            
        directory_path.mkdir(parents=True, exist_ok=True)
        speak(f"Created directory: {directory_path}")
        return True
    except Exception as e:
        speak(f"An error occurred while creating the directory: {e}")
        print(f"An error occurred while creating the directory: {e}")
        return False

def list_directory(directory_path='.'):
    """Lists the contents of a directory."""
    try:
        directory_path = Path(directory_path)
        if not directory_path.exists():
            speak(f"Directory {directory_path} does not exist.")
            return False
            
        if not directory_path.is_dir():
            speak(f"{directory_path} is not a directory.")
            return False
            
        # Get files and directories
        items = list(directory_path.iterdir())
        files = [item for item in items if item.is_file()]
        dirs = [item for item in items if item.is_dir()]
        
        # Speak summary
        speak(f"Directory {directory_path} contains {len(files)} files and {len(dirs)} subdirectories.")
        
        # List subdirectories
        if dirs:
            speak("Subdirectories:")
            for d in dirs:
                print(f"📁 {d.name}")
                
        # List files
        if files:
            speak("Files:")
            for f in files:
                size_kb = f.stat().st_size / 1024
                print(f"📄 {f.name} ({size_kb:.1f} KB)")
                
        return True
    except Exception as e:
        speak(f"An error occurred while listing the directory: {e}")
        print(f"An error occurred while listing the directory: {e}")
        return False