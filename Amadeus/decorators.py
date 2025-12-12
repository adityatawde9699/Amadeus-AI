# decorators.py
"""
Utility decorators for stability, validation, and error handling.
These decorators help improve the robustness of Amadeus operations.
"""

import asyncio
import functools
import logging
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union

import config

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_on_failure(
    max_retries: Optional[int] = None,
    delay: Optional[float] = None,
    exceptions: tuple = (Exception,),
    exponential_backoff: bool = True
):
    """
    Retry decorator for flaky operations.
    
    Args:
        max_retries: Maximum number of retry attempts (default from config)
        delay: Base delay between retries in seconds (default from config)
        exceptions: Tuple of exception types to catch and retry
        exponential_backoff: Whether to use exponential backoff for delays
    
    Returns:
        Decorated function that retries on specified exceptions
    
    Usage:
        @retry_on_failure(max_retries=3)
        async def flaky_api_call():
            ...
    """
    _max_retries = max_retries or getattr(config, 'DB_MAX_RETRIES', 3)
    _delay = delay or getattr(config, 'DB_RETRY_DELAY', 0.5)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(_max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < _max_retries:
                        wait_time = _delay * (2 ** attempt if exponential_backoff else 1)
                        logger.warning(
                            f"Attempt {attempt + 1}/{_max_retries + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {_max_retries + 1} attempts failed for {func.__name__}")
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            last_exception = None
            for attempt in range(_max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < _max_retries:
                        wait_time = _delay * (2 ** attempt if exponential_backoff else 1)
                        logger.warning(
                            f"Attempt {attempt + 1}/{_max_retries + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {wait_time:.2f}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {_max_retries + 1} attempts failed for {func.__name__}")
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def graceful_fallback(fallback_value: Any, log_level: str = "warning"):
    """
    Return fallback value on any exception instead of raising.
    
    Args:
        fallback_value: Value to return if function fails
        log_level: Logging level for the error message
    
    Usage:
        @graceful_fallback("Unable to retrieve data")
        async def get_data():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                log_func = getattr(logger, log_level, logger.warning)
                log_func(f"{func.__name__} failed gracefully: {e}")
                return fallback_value
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_func = getattr(logger, log_level, logger.warning)
                log_func(f"{func.__name__} failed gracefully: {e}")
                return fallback_value
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def validate_input(**validators: Callable[[Any], bool]):
    """
    Input validation decorator with type checking.
    
    Args:
        **validators: Mapping of parameter names to validation functions
                     Each validator should return True if valid, False otherwise
    
    Usage:
        @validate_input(
            title=lambda x: isinstance(x, str) and len(x) > 0,
            count=lambda x: isinstance(x, int) and x > 0
        )
        async def create_item(title: str, count: int):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Validate keyword arguments
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    value = kwargs[param_name]
                    if not validator(value):
                        error_msg = f"Invalid value for '{param_name}': {value}"
                        logger.warning(error_msg)
                        return {"error": error_msg}
            return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    value = kwargs[param_name]
                    if not validator(value):
                        error_msg = f"Invalid value for '{param_name}': {value}"
                        logger.warning(error_msg)
                        return {"error": error_msg}
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def require_api_key(api_key_name: str, fallback_message: Optional[str] = None):
    """
    Decorator to check if an API key is configured before executing.
    
    Args:
        api_key_name: Name of the API key attribute in config
        fallback_message: Message to return if API key is missing
    
    Usage:
        @require_api_key('WEATHER_API_KEY', 'Weather service unavailable')
        async def get_weather():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            api_key = getattr(config, api_key_name, None)
            if not api_key:
                msg = fallback_message or f"{api_key_name} not configured. Feature unavailable."
                logger.info(msg)
                return msg
            return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            api_key = getattr(config, api_key_name, None)
            if not api_key:
                msg = fallback_message or f"{api_key_name} not configured. Feature unavailable."
                logger.info(msg)
                return msg
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def log_execution(include_args: bool = False, include_result: bool = False):
    """
    Log function execution for debugging and monitoring.
    
    Args:
        include_args: Whether to log function arguments
        include_result: Whether to log the return value
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            if include_args:
                logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
            else:
                logger.debug(f"Calling {func.__name__}")
            
            result = await func(*args, **kwargs)
            
            if include_result:
                logger.debug(f"{func.__name__} returned: {result}")
            else:
                logger.debug(f"{func.__name__} completed")
            
            return result
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            if include_args:
                logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
            else:
                logger.debug(f"Calling {func.__name__}")
            
            result = func(*args, **kwargs)
            
            if include_result:
                logger.debug(f"{func.__name__} returned: {result}")
            else:
                logger.debug(f"{func.__name__} completed")
            
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# Common validators for validate_input
class Validators:
    """Collection of common validation functions."""
    
    @staticmethod
    def non_empty_string(value: Any) -> bool:
        """Check if value is a non-empty string."""
        return isinstance(value, str) and len(value.strip()) > 0
    
    @staticmethod
    def positive_int(value: Any) -> bool:
        """Check if value is a positive integer."""
        return isinstance(value, int) and value > 0
    
    @staticmethod
    def non_negative_int(value: Any) -> bool:
        """Check if value is zero or positive integer."""
        return isinstance(value, int) and value >= 0
    
    @staticmethod
    def in_range(min_val: float, max_val: float) -> Callable[[Any], bool]:
        """Return validator that checks if value is in range."""
        def validator(value: Any) -> bool:
            try:
                return min_val <= float(value) <= max_val
            except (TypeError, ValueError):
                return False
        return validator
    
    @staticmethod
    def one_of(*choices) -> Callable[[Any], bool]:
        """Return validator that checks if value is one of the choices."""
        def validator(value: Any) -> bool:
            return value in choices
        return validator
