"""
Custom exceptions for API error handling.
"""

from fastapi import HTTPException, status


class AmadeusException(HTTPException):
    """Base exception for Amadeus API."""
    
    def __init__(self, detail: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(status_code=status_code, detail=detail)


class ValidationError(AmadeusException):
    """Raised when input validation fails."""
    
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=status.HTTP_400_BAD_REQUEST)


class NotFoundError(AmadeusException):
    """Raised when a resource is not found."""
    
    def __init__(self, resource: str, identifier: str):
        detail = f"{resource} with identifier '{identifier}' not found"
        super().__init__(detail=detail, status_code=status.HTTP_404_NOT_FOUND)


class PermissionError(AmadeusException):
    """Raised when a permission check fails."""
    
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=status.HTTP_403_FORBIDDEN)


class RateLimitError(AmadeusException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, detail: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(detail=detail, status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after


class DatabaseError(AmadeusException):
    """Raised when a database operation fails."""
    
    def __init__(self, detail: str = "Database operation failed"):
        super().__init__(detail=detail, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

