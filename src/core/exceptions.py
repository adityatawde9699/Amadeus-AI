"""
Domain-specific exceptions for Amadeus AI Assistant.

This module defines a hierarchy of exceptions that are meaningful
in the context of the Amadeus domain. Infrastructure and framework
exceptions should be caught and wrapped in these domain exceptions.

Usage:
    from src.core.exceptions import ToolExecutionError, ConfigurationError
    
    raise ToolExecutionError("open_chrome", "Chrome is not installed")
"""

from typing import Any


class AmadeusError(Exception):
    """
    Base exception for all Amadeus-related errors.
    
    All domain-specific exceptions should inherit from this class
    to enable consistent error handling at API boundaries.
    """
    
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert exception to a dictionary for API responses."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# CONFIGURATION ERRORS
# =============================================================================

class ConfigurationError(AmadeusError):
    """Raised when there's a configuration problem."""
    
    def __init__(self, message: str, config_key: str | None = None):
        super().__init__(
            message,
            details={"config_key": config_key} if config_key else None
        )
        self.config_key = config_key


class MissingAPIKeyError(ConfigurationError):
    """Raised when a required API key is missing."""
    
    def __init__(self, key_name: str):
        super().__init__(
            f"Missing required API key: {key_name}",
            config_key=key_name
        )
        self.key_name = key_name


# =============================================================================
# TOOL EXECUTION ERRORS
# =============================================================================

class ToolExecutionError(AmadeusError):
    """Raised when a tool fails to execute properly."""
    
    def __init__(self, tool_name: str, reason: str, cause: Exception | None = None):
        super().__init__(
            f"Tool '{tool_name}' failed: {reason}",
            details={"tool_name": tool_name, "reason": reason}
        )
        self.tool_name = tool_name
        self.reason = reason
        self.cause = cause


class ToolNotFoundError(ToolExecutionError):
    """Raised when a requested tool doesn't exist."""
    
    def __init__(self, tool_name: str):
        super().__init__(tool_name, f"Tool '{tool_name}' not found")


class ToolTimeoutError(ToolExecutionError):
    """Raised when a tool execution times out."""
    
    def __init__(self, tool_name: str, timeout_seconds: float):
        super().__init__(
            tool_name,
            f"Execution timed out after {timeout_seconds} seconds"
        )
        self.timeout_seconds = timeout_seconds


class ToolArgumentError(ToolExecutionError):
    """Raised when tool arguments are invalid."""
    
    def __init__(self, tool_name: str, argument: str, reason: str):
        super().__init__(
            tool_name,
            f"Invalid argument '{argument}': {reason}"
        )
        self.argument = argument


# =============================================================================
# PERSISTENCE ERRORS
# =============================================================================

class PersistenceError(AmadeusError):
    """Base exception for database/storage errors."""
    pass


class EntityNotFoundError(PersistenceError):
    """Raised when a requested entity doesn't exist."""
    
    def __init__(self, entity_type: str, entity_id: Any):
        super().__init__(
            f"{entity_type} with id '{entity_id}' not found",
            details={"entity_type": entity_type, "entity_id": str(entity_id)}
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class DuplicateEntityError(PersistenceError):
    """Raised when attempting to create a duplicate entity."""
    
    def __init__(self, entity_type: str, identifier: str):
        super().__init__(
            f"{entity_type} already exists: {identifier}",
            details={"entity_type": entity_type, "identifier": identifier}
        )


class DatabaseConnectionError(PersistenceError):
    """Raised when database connection fails."""
    
    def __init__(self, message: str = "Failed to connect to database"):
        super().__init__(message)


# =============================================================================
# VOICE/SPEECH ERRORS
# =============================================================================

class VoiceError(AmadeusError):
    """Base exception for voice-related errors."""
    pass


class SpeechRecognitionError(VoiceError):
    """Raised when speech recognition fails."""
    
    def __init__(self, reason: str, timeout: bool = False):
        super().__init__(
            f"Speech recognition failed: {reason}",
            details={"timeout": timeout}
        )
        self.timeout = timeout


class TextToSpeechError(VoiceError):
    """Raised when text-to-speech fails."""
    
    def __init__(self, reason: str):
        super().__init__(f"Text-to-speech failed: {reason}")


class VoiceServiceUnavailableError(VoiceError):
    """Raised when voice services are not available."""
    
    def __init__(self, missing_dependency: str | None = None):
        message = "Voice service is not available"
        if missing_dependency:
            message += f" (missing: {missing_dependency})"
        super().__init__(
            message,
            details={"missing_dependency": missing_dependency}
        )


# =============================================================================
# LLM/AI ERRORS
# =============================================================================

class LLMError(AmadeusError):
    """Base exception for LLM-related errors."""
    pass


class LLMConnectionError(LLMError):
    """Raised when connection to LLM service fails."""
    
    def __init__(self, service: str, reason: str):
        super().__init__(
            f"Failed to connect to {service}: {reason}",
            details={"service": service}
        )
        self.service = service


class LLMRateLimitError(LLMError):
    """Raised when LLM rate limit is exceeded."""
    
    def __init__(self, service: str, retry_after: float | None = None):
        message = f"{service} rate limit exceeded"
        if retry_after:
            message += f", retry after {retry_after}s"
        super().__init__(
            message,
            details={"service": service, "retry_after": retry_after}
        )
        self.retry_after = retry_after


class LLMResponseError(LLMError):
    """Raised when LLM response is invalid or unexpected."""
    
    def __init__(self, reason: str):
        super().__init__(f"Invalid LLM response: {reason}")


# =============================================================================
# VALIDATION ERRORS
# =============================================================================

class ValidationError(AmadeusError):
    """Raised when input validation fails."""
    
    def __init__(self, field: str, reason: str):
        super().__init__(
            f"Validation failed for '{field}': {reason}",
            details={"field": field, "reason": reason}
        )
        self.field = field
        self.reason = reason


class InputTooLongError(ValidationError):
    """Raised when input exceeds maximum length."""
    
    def __init__(self, field: str, max_length: int, actual_length: int):
        super().__init__(
            field,
            f"exceeds maximum length of {max_length} (got {actual_length})"
        )
        self.max_length = max_length
        self.actual_length = actual_length


# =============================================================================
# RATE LIMITING ERRORS
# =============================================================================

class RateLimitExceededError(AmadeusError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, limit: int, window_seconds: int, retry_after: float | None = None):
        super().__init__(
            f"Rate limit of {limit} requests per {window_seconds}s exceeded",
            details={
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after": retry_after
            }
        )
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
