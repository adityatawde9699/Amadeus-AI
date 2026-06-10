"""
FastAPI application server for Amadeus AI Assistant (Transport layer).

This is the main entry point for the API layer transport.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt as _jose_jwt
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.api.auth.manager import auth_backend, fastapi_users
from src.api.auth.schemas import UserCreate, UserRead
from src.api.middleware.audit_logger import AuditLoggerMiddleware
from src.api.middleware.tracing import TracingMiddleware
from src.container import global_container
from src.core.config import get_settings
from src.core.exceptions import AmadeusError


import logging
import logging.handlers


settings = get_settings()

# Create logs directory
log_dir = settings.BASE_DIR / "data" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

# Standard logging configuration (which structlog will use)
file_handler = logging.handlers.RotatingFileHandler(
    log_dir / "amadeus.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
console_handler = logging.StreamHandler()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    handlers=[console_handler, file_handler],
)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


def get_rate_limit_key(request: Request) -> str:
    """
    Rate-limiting key function: use JWT `sub` claim (user ID) when present,
    falling back to remote IP for unauthenticated requests.

    This prevents a single user behind a shared IP from being blocked by
    another user's traffic, and stops single users from abusing shared IPs.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            # Decode WITHOUT verification — we only need the `sub` claim
            # as a stable key. The actual signature check happens in the
            # authentication middleware.
            payload = _jose_jwt.get_unverified_claims(token)
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass  # Fall through to IP-based key
    return get_remote_address(request)


if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENV,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# Setup OpenTelemetry — only wire the OTLP exporter if the collector is reachable.
# Without this guard, the gRPC exporter retries every ~1s and floods the logs.
def _otlp_collector_reachable(host: str = "localhost", port: int = 4317) -> bool:
    """Quick TCP probe to see if the OTLP collector is listening."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False

resource = Resource.create({SERVICE_NAME: settings.ASSISTANT_NAME})
provider = TracerProvider(resource=resource)

if _otlp_collector_reachable():
    otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    logging.getLogger(__name__).info(
        "OpenTelemetry: OTLP collector found at localhost:4317 — tracing enabled."
    )
else:
    logging.getLogger(__name__).info(
        "OpenTelemetry: No OTLP collector at localhost:4317 — using NoOp tracer (silent)."
    )

trace.set_tracer_provider(provider)


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Delegates the shared runtime lifecycle (DB, runtime services, Telegram
    polling, background loops) to the transport-agnostic ``RuntimeHost`` and
    layers on only the API-specific wiring — the HITL confirmation callback
    used by the ``/confirm`` route.
    """
    # Startup
    logger.info("Starting %s API v%s", settings.ASSISTANT_NAME, settings.ASSISTANT_VERSION)

    from src.runtime.host import RuntimeHost

    host = RuntimeHost(settings)
    await host.start()
    app.state.host = host
    app.state.runtime = host.runtime

    # Initialize HITL Confirmation callback singleton (API-only).
    # Stored on app.state so the /confirm route handler can access it
    # via the get_confirmation_callback dependency. The Telegram transport
    # injects its own TelegramConfirmationCallback per-message, so this is
    # only used by the REST /confirm flow.
    from src.container import inject_confirmation_callback
    from src.infra.tools.confirmation import APIConfirmationCallback

    confirmation_callback = APIConfirmationCallback(
        timeout_seconds=60  # User has 60s to approve/deny before auto-deny
    )
    app.state.confirmation_callback = confirmation_callback
    inject_confirmation_callback(confirmation_callback)
    logger.info("HITL confirmation gate initialized (timeout=60s)")

    logger.info("API ready at http://%s:%s", settings.API_HOST, settings.API_PORT)

    yield

    # Shutdown
    logger.info("Shutting down API...")
    await host.stop()
    logger.info("Shutdown complete")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title=f"{settings.ASSISTANT_NAME} AI Assistant API",
    version=settings.ASSISTANT_VERSION,
    description="RESTful API for the Amadeus AI Assistant.",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.container = global_container  # type: ignore[attr-defined]


# =============================================================================
# MIDDLEWARE
# =============================================================================

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Audit logging middleware (request ID + timing headers)
app.add_middleware(TracingMiddleware)
app.add_middleware(AuditLoggerMiddleware)

# Rate limiting — per user (JWT sub) with IP fallback
# P6-T5: Probe Redis connectivity at startup; fall back to in-memory
# storage if Redis is unavailable so the server starts cleanly.
_rate_limit_storage: str | None = None
_configured_redis_url = settings.REDIS_URL
if _configured_redis_url:
    try:
        import redis as _redis_mod
        _r = _redis_mod.from_url(_configured_redis_url, socket_connect_timeout=2)
        _r.ping()
        _rate_limit_storage = _configured_redis_url
        logger.info("SlowAPI: using Redis storage (%s)", _configured_redis_url)
    except Exception as _redis_err:
        logger.warning(
            "SlowAPI: Redis unreachable (%s) — falling back to in-memory rate-limit storage. "
            "Limits will not persist across workers.",
            _redis_err,
        )
        _rate_limit_storage = None

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[f"{settings.RATE_LIMIT_REQUESTS}/minute"],
    storage_uri=_rate_limit_storage,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Prometheus Metrics (imported from infra layer — single source of truth)
from prometheus_fastapi_instrumentator import Instrumentator

from src.infra.metrics import (
    amadeus_llm_calls_total,  # noqa: F401 — imported for re-export / side-effect registration
)


Instrumentator().instrument(app).expose(app, endpoint="/api/v1/metrics", tags=["System"])


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================


@app.exception_handler(AmadeusError)
async def amadeus_exception_handler(request: Request, exc: AmadeusError) -> JSONResponse:
    """Handle domain-specific exceptions."""
    logger.warning("Domain error: %s", exc.message)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error("Unexpected error: %s", exc, exc_info=True)

    if getattr(settings, "ALLOW_DEBUG_RESPONSES", False):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "InternalError", "message": str(exc)},
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "InternalError", "message": "An unexpected error occurred"},
    )


# =============================================================================
# HEALTH CHECK ROUTES
# =============================================================================


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """
    Health check endpoint.

    Returns basic health status for load balancers and monitoring.
    """
    return {
        "status": "healthy",
        "service": settings.ASSISTANT_NAME,
        "version": settings.ASSISTANT_VERSION,
        "environment": settings.ENV,
    }


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Root endpoint with API information."""
    return {
        "message": f"Welcome to {settings.ASSISTANT_NAME} API",
        "version": settings.ASSISTANT_VERSION,
        "docs": "/docs" if settings.DEBUG else "Disabled in production",
    }


if settings.is_development:

    @app.get("/sentry-debug", include_in_schema=False)
    async def trigger_error() -> None:
        raise ZeroDivisionError("Sentry test")


# =============================================================================
# ROUTE REGISTRATION
# =============================================================================

# Import and register route modules
from fastapi import Depends

from src.api.middleware.authentication import verify_jwt_token
from src.api.middleware.rbac import RequireUser
from src.api.routes import (
    chat,
    confirm,
    health,
    llm,
    messaging,
    readiness,
    tasks,
)


# Disable auth for health + LLM usage, enable for everything else
app.include_router(health.router, prefix="/api/v1", tags=["System"])
app.include_router(llm.router, prefix="/api/v1", tags=["LLM"])  # No auth — informational
# Phase 12: Liveness + Readiness probes (no auth — used by container orchestrators)
app.include_router(readiness.router, prefix="/api/v1", tags=["Health"])

# Protected routes (Require basic User role)
protected_deps = [Depends(RequireUser)]
app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"], dependencies=protected_deps)
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"], dependencies=protected_deps)


# FastAPI-Users Auth
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/v1/auth/jwt",
    tags=["Auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/v1/auth",
    tags=["Auth"],
)

# Outbound messaging dispatch (requires JWT auth)
app.include_router(
    messaging.router, prefix="/api/v1", tags=["Messaging"], dependencies=[Depends(verify_jwt_token)]
)

# HITL Confirmation endpoint — requires JWT auth (user must be authenticated to approve/deny)
app.include_router(
    confirm.router,
    prefix="/api/v1",
    tags=["Confirmation"],
    dependencies=[Depends(verify_jwt_token)],
)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Run the API server directly."""
    import uvicorn

    uvicorn.run(
        "src.transports.fastapi_transport:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        reload_dirs=["src"] if settings.DEBUG else None,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
