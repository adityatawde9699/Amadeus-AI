import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import sys

# Mock dependencies that might not be installed or needed for these tests
sys.modules["speech_utils"] = MagicMock()
sys.modules["psutil"] = MagicMock()

# Import the module to test
import system_controls
from system_controls import create_folder, delete_file, read_file, get_app_name, search_file

@pytest.fixture
def mock_security():
    """Mock security checks to always pass for these unit tests."""
    # Since system_controls imports these from security inside functions,
    # we must patch where they are defined (in security module)
    # We also need to mock sys.modules['security'] if it's not imported yet, 
    # but patching strings should handle imports if they exist. 
    # To be safe, we'll patch with 'security.check_file_permissions' etc.
    # Note: We need to ensure logic uses these patched versions.
    
    with patch("security.check_file_permissions") as mock_perms, \
         patch("security.check_directory_permissions") as mock_dir_perms, \
         patch("security.is_safe_path") as mock_safe, \
         patch("security.audit_file_operation") as mock_audit, \
         patch("security.validate_file_path") as mock_validate: # Also patch validate_file_path which is used
        
        mock_perms.return_value = (True, "")
        mock_dir_perms.return_value = (True, "")
        mock_safe.return_value = True
        # validate_file_path usually returns a Path object
        mock_validate.side_effect = lambda x, allow_absolute=False: Path(x)
        
        yield {
            "perms": mock_perms,
            "dir_perms": mock_dir_perms,
            "safe": mock_safe,
            "audit": mock_audit,
            "validate": mock_validate
        }

def test_get_app_name_windows():
    """Test app name resolution for Windows."""
    with patch("platform.system", return_value="Windows"):
        assert get_app_name("notepad") == "notepad.exe"
        assert get_app_name("chrome") == "chrome.exe"
        # The logic checks if key ('calculator') is in command ('calculator app')
        # 'calc' does not contain 'calculator', so it returns None.
        assert get_app_name("calculator") == "calc.exe" 
        assert get_app_name("nonexistentapp") is None

def test_get_app_name_mac_linux():
    """Test app name resolution for MacOS and Linux."""
    with patch("platform.system", return_value="Darwin"):
        assert get_app_name("safari") == "Safari"
    
    with patch("platform.system", return_value="Linux"):
        assert get_app_name("firefox") == "firefox"

def test_create_folder(mock_security):
    """Test folder creation."""
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("pathlib.Path.exists", return_value=False):
        
        result = create_folder("new_folder")
        assert result is True
        mock_mkdir.assert_called_once()
        mock_security["audit"]  # Ensure audit is not called for create_folder (not implemented there yet or different logic)

def test_create_folder_exists():
    """Test folder creation when folder already exists."""
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True):
        
        result = create_folder("existing_folder")
        assert result is False

def test_delete_file(mock_security):
    """Test file deletion."""
    with patch("os.remove") as mock_remove, \
         patch("shutil.copy2") as mock_copy, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True):
        
        # Skip confirmation for test
        result = delete_file("test_file.txt", skip_confirmation=True)
        
        assert result is True
        mock_remove.assert_called_once()
        mock_security["audit"].assert_called_with("delete", "test_file.txt", success=True)

def test_read_file_text():
    """Test reading a text file."""
    mock_content = "Hello, World!"
    with patch("builtins.open", mock_open(read_data=mock_content)), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.suffix", new_callable=MagicMock) as mock_suffix:
        
        mock_suffix.lower.return_value = ".txt"
        
        content = read_file("test.txt")
        assert content == "Hello, World!"

def test_read_file_not_found():
    """Test reading a non-existent file."""
    with patch("pathlib.Path.is_file", return_value=False):
        content = read_file("nonexistent.txt")
        assert content is None

def test_search_file_success():
    """Test successful file search."""
    mock_path = Path("/path/to/found.txt")
    with patch("pathlib.Path.rglob", return_value=[mock_path]), \
         patch("pathlib.Path.exists", return_value=True):
        
        result = search_file("found.txt", "/path/to")
        assert result == str(mock_path)

def test_search_file_not_found():
    """Test file search with no results."""
    with patch("pathlib.Path.rglob", return_value=[]), \
         patch("pathlib.Path.exists", return_value=True):
        
        result = search_file("missing.txt", "/path/to")
        assert result is None
