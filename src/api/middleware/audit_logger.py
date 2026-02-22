"""
Audit Logging Middleware for Amadeus AI.

Logs every API request and response with a unique request_id for tracing.
Never logs request body (may contain sensitive user data or API keys).

Structured fields logged per request:
- request_id: UUID for request tracing
- method: HTTP method
- path: URL path
- client_ip: Requester IP
- user_agent: Truncated user-agent string
- status_code: HTTP response status
- duration_ms: Request processing time
"""

import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


audit_log = structlog.get_logger("amadeus.audit")


class AuditLoggerMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that logs every request/response pair.

    Design choices:
    - Uses structlog for structured JSON output in production
    - Never logs request bodies or auth headers (privacy + security)
    - Adds X-Request-ID header to all responses for tracing
    """

    # Paths to skip (health checks produce too much noise)
    SKIP_PATHS: frozenset[str] = frozenset({"/health", "/", "/api/v1/metrics"})

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Skip noisy health + metrics paths
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        # Log incoming request (no body, no auth headers)
        audit_log.info(
            "api_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "")[:100],
        )

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Log response
        audit_log.info(
            "api_response",
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Add tracing headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"

        return response
