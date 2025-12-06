"""
Security utilities for input validation, sanitization, and permission checks.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from functools import wraps
from fastapi import HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
import config

logger = logging.getLogger(__name__)

# ============================================================================
# API KEY AUTHENTICATION
# ============================================================================

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> str:
    """
    Validate API key from request header.
    
    Args:
        api_key: API key from request header
        
    Returns:
        Validated API key
        
    Raises:
        HTTPException: If API key is missing or invalid
    """
    # Get API key from environment or config
    valid_api_key = os.getenv('API_KEY', config.ASSISTANT_NAME.lower() + '_api_key_2024')
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key is required. Provide it in the X-API-Key header."
        )
    
    if api_key != valid_api_key:
        logger.warning(f"Invalid API key attempt from client")
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )
    
    return api_key


# ============================================================================
# INPUT VALIDATION AND SANITIZATION
# ============================================================================

def sanitize_string(value: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize a string input by removing dangerous characters and limiting length.
    
    Args:
        value: Input string to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        raise ValueError("Input must be a string")
    
    # Remove null bytes and control characters (except newline, tab, carriage return)
    sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', value)
    
    # Remove leading/trailing whitespace
    sanitized = sanitized.strip()
    
    # Limit length if specified
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        logger.warning(f"String truncated to {max_length} characters")
    
    return sanitized


def validate_file_path(file_path: str, allow_absolute: bool = False) -> Path:
    """
    Validate and normalize a file path, preventing directory traversal attacks.
    
    Args:
        file_path: File path to validate
        allow_absolute: Whether to allow absolute paths
        
    Returns:
        Normalized Path object
        
    Raises:
        ValueError: If path is invalid or contains dangerous patterns
    """
    if not file_path or not file_path.strip():
        raise ValueError("File path cannot be empty")
        
    # Check for null bytes before sanitization (as sanitization removes them)
    if '\x00' in file_path:
        raise ValueError("Invalid file path: contains null bytes")
    
    # Sanitize the path
    sanitized = sanitize_string(file_path, max_length=1000)
    
    # Check for dangerous patterns
    dangerous_patterns = [
        '../', '..\\',  # Directory traversal
        '//', '\\\\',   # Multiple separators
        '\x00',         # Null bytes
    ]
    
    for pattern in dangerous_patterns:
        if pattern in sanitized:
            raise ValueError(f"Invalid file path: contains dangerous pattern '{pattern}'")
    
    # Convert to Path object
    path = Path(sanitized)
    
    # Resolve to absolute path
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid file path: {e}")
    
    # If absolute paths not allowed, ensure path is relative
    if not allow_absolute and resolved.is_absolute():
        # For security, we might want to restrict to a specific base directory
        base_dir = Path.cwd()
        try:
            resolved.relative_to(base_dir)
        except ValueError:
            raise ValueError("File path must be within the application directory")
    
    return resolved


def validate_directory_path(dir_path: str, must_exist: bool = False) -> Path:
    """
    Validate and normalize a directory path.
    
    Args:
        dir_path: Directory path to validate
        must_exist: Whether the directory must exist
        
    Returns:
        Normalized Path object
        
    Raises:
        ValueError: If path is invalid
    """
    path = validate_file_path(dir_path, allow_absolute=True)
    
    if must_exist and not path.exists():
        raise ValueError(f"Directory does not exist: {dir_path}")
    
    if path.exists() and not path.is_dir():
        raise ValueError(f"Path exists but is not a directory: {dir_path}")
    
    return path


# ============================================================================
# PERMISSION CHECKS
# ============================================================================

def check_file_permissions(file_path: Path, operation: str = "read") -> Tuple[bool, str]:
    """
    Check if a file operation is permitted.
    
    Args:
        file_path: Path to the file
        operation: Operation type ('read', 'write', 'delete')
        
    Returns:
        Tuple of (is_allowed, reason)
    """
    if not file_path.exists():
        if operation == "read":
            return False, "File does not exist"
        # Write/delete operations can proceed if file doesn't exist (for create)
        return True, ""
    
    if not file_path.is_file():
        return False, "Path is not a file"
    
    # Check read permission
    if operation == "read":
        if not os.access(file_path, os.R_OK):
            return False, "Read permission denied"
        return True, ""
    
    # Check write permission
    if operation in ("write", "delete"):
        # Check if file is writable
        if file_path.exists() and not os.access(file_path, os.W_OK):
            return False, "Write permission denied"
        
        # Check if parent directory is writable
        parent_dir = file_path.parent
        if not os.access(parent_dir, os.W_OK):
            return False, "Parent directory is not writable"
        
        return True, ""
    
    return False, f"Unknown operation: {operation}"


def check_directory_permissions(dir_path: Path, operation: str = "read") -> Tuple[bool, str]:
    """
    Check if a directory operation is permitted.
    
    Args:
        dir_path: Path to the directory
        operation: Operation type ('read', 'write', 'create')
        
    Returns:
        Tuple of (is_allowed, reason)
    """
    if operation == "create":
        # Check if parent directory is writable
        parent_dir = dir_path.parent
        if not parent_dir.exists():
            return False, "Parent directory does not exist"
        if not os.access(parent_dir, os.W_OK):
            return False, "Parent directory is not writable"
        return True, ""
    
    if not dir_path.exists():
        return False, "Directory does not exist"
    
    if not dir_path.is_dir():
        return False, "Path is not a directory"
    
    if operation == "read":
        if not os.access(dir_path, os.R_OK):
            return False, "Read permission denied"
        return True, ""
    
    if operation == "write":
        if not os.access(dir_path, os.W_OK):
            return False, "Write permission denied"
        return True, ""
    
    return False, f"Unknown operation: {operation}"


# ============================================================================
# SECURITY AUDIT HELPERS
# ============================================================================

def audit_file_operation(operation: str, file_path: str, user: Optional[str] = None, success: bool = True):
    """
    Log file operations for security auditing.
    
    Args:
        operation: Operation type (read, write, delete, etc.)
        file_path: Path to the file
        user: User identifier (if available)
        success: Whether the operation was successful
    """
    status = "SUCCESS" if success else "FAILED"
    user_info = f" by {user}" if user else ""
    logger.info(f"FILE_OPERATION: {operation.upper()} {file_path} {status}{user_info}")


def is_safe_path(path: Path, base_path: Optional[Path] = None) -> bool:
    """
    Check if a path is safe (within allowed directory).
    
    Args:
        path: Path to check
        base_path: Base directory to restrict to (default: current working directory)
        
    Returns:
        True if path is safe, False otherwise
    """
    if base_path is None:
        base_path = Path.cwd()
    
    try:
        path.resolve().relative_to(base_path.resolve())
        return True
    except ValueError:
        return False


def get_safe_base_directory() -> Path:
    """
    Get the safe base directory for file operations.
    Can be configured via environment variable.
    
    Returns:
        Base directory path
    """
    base_dir = os.getenv('AMADEUS_SAFE_BASE_DIR', str(Path.cwd()))
    return Path(base_dir).resolve()

