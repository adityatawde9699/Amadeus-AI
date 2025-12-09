"""
Middleware for rate limiting and request processing.
"""

import os
import time
import logging
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import config

logger = logging.getLogger(__name__)

# ============================================================================
# RATE LIMITING
# ============================================================================

class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self):
        self.requests: Dict[str, list] = defaultdict(list)
        self.max_requests = int(os.getenv('API_RATE_LIMIT_REQUESTS', '100'))
        self.window_seconds = int(os.getenv('API_RATE_LIMIT_WINDOW', '60'))
    
    def is_allowed(self, client_id: str) -> Tuple[bool, int]:
        """
        Check if a request is allowed based on rate limits.
        
        Args:
            client_id: Unique identifier for the client (IP address or API key)
            
        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # Clean old requests outside the window
        self.requests[client_id] = [
            req_time for req_time in self.requests[client_id]
            if req_time > window_start
        ]
        
        # Check if limit exceeded
        if len(self.requests[client_id]) >= self.max_requests:
            remaining = 0
            return False, remaining
        
        # Add current request
        self.requests[client_id].append(now)
        remaining = self.max_requests - len(self.requests[client_id])
        
        return True, remaining
    
    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for a client."""
        now = time.time()
        window_start = now - self.window_seconds
        
        self.requests[client_id] = [
            req_time for req_time in self.requests[client_id]
            if req_time > window_start
        ]
        
        return max(0, self.max_requests - len(self.requests[client_id]))


# Global rate limiter instance
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limiting."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health check and docs endpoints
        if request.url.path in ['/health', '/docs', '/openapi.json', '/redoc']:
            return await call_next(request)
        
        # Get client identifier (IP address or API key)
        client_id = request.client.host if request.client else "unknown"
        
        # Check for API key in header (use it as client_id if present)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            client_id = f"api_key:{api_key[:8]}"  # Use first 8 chars for privacy
        
        # Check rate limit
        is_allowed, remaining = rate_limiter.is_allowed(client_id)
        
        # Add rate limit headers
        response = await call_next(request) if is_allowed else None
        
        if not is_allowed:
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Maximum {rate_limiter.max_requests} requests per {rate_limiter.window_seconds} seconds",
                    "retry_after": rate_limiter.window_seconds
                }
            )
        
        # Add rate limit headers to response
        if response:
            response.headers["X-RateLimit-Limit"] = str(rate_limiter.max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Window"] = str(rate_limiter.window_seconds)
        
        return response


# ============================================================================
# ERROR HANDLING MIDDLEWARE
# ============================================================================

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for consistent error handling."""
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            # Re-raise HTTP exceptions (they're already properly formatted)
            raise
        except ValueError as e:
            # Handle validation errors
            logger.warning(f"Validation error: {e}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": "Validation error",
                    "detail": str(e),
                    "status_code": 400
                }
            )
        except PermissionError as e:
            # Handle permission errors
            logger.warning(f"Permission error: {e}")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "Permission denied",
                    "detail": str(e),
                    "status_code": 403
                }
            )
        except FileNotFoundError as e:
            # Handle file not found errors
            logger.warning(f"File not found: {e}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "Resource not found",
                    "detail": str(e),
                    "status_code": 404
                }
            )
        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal server error",
                    "detail": "An unexpected error occurred. Please try again later.",
                    "status_code": 500
                }
            )