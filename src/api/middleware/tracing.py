import logging
from collections.abc import Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)

class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))

            # The span ID will be our trace ID for this request context
            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id

            response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)
            return response
