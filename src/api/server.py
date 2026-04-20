"""
FastAPI application server for Amadeus AI Assistant.

This is the main entry point for the API layer. It sets up the
FastAPI application with proper lifespan management, middleware,
and route registration.

Usage:
    # Run with uvicorn
    uvicorn src.api.server:app --reload

    # Or run directly
    python -m src.api.server
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt as _jose_jwt
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.api.auth.manager import auth_backend, fastapi_users
from src.api.auth.schemas import UserCreate, UserRead
from src.api.middleware.audit_logger import AuditLoggerMiddleware
from src.core.config import get_settings, validate_settings
from src.core.exceptions import AmadeusError
from src.infra.persistence.database import close_db, init_db


# Global scheduler instance
scheduler = AsyncIOScheduler()


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
        traces_sample_rate=1.0,
        send_default_pii=True,
    )


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for the application.
    """
    # Startup
    logger.info(f"Starting {settings.ASSISTANT_NAME} API v{settings.ASSISTANT_VERSION}")

    # Validate configuration
    validation = validate_settings()
    if validation["errors"]:
        logger.error(f"Configuration errors: {validation['errors']}")
        if settings.is_production:
            raise RuntimeError("Configuration errors in production")
    for warning in validation.get("warnings", []):
        logger.warning(f"Config warning: {warning}")

    # Run database migrations automatically
    try:
        from alembic import command
        from alembic.config import Config

        logger.info("Running database migrations...")
        alembic_cfg_path = settings.BASE_DIR / "alembic.ini"
        alembic_script_location = settings.BASE_DIR / "alembic"

        if alembic_cfg_path.exists() and alembic_script_location.exists():
            import asyncio

            alembic_cfg = Config(str(alembic_cfg_path))
            alembic_cfg.set_main_option("script_location", str(alembic_script_location))
            await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
            logger.info("Database migrations complete")
        else:
            logger.warning(
                f"Alembic config or scripts missing at {settings.BASE_DIR}. Skipping migrations."
            )
    except Exception as e:
        logger.error(f"Failed to run migrations: {e}")
        if settings.is_production:
            raise

    # Initialize database
    await init_db()

    # Initialize HITL Confirmation callback singleton.
    # Stored on app.state so the /confirm route handler can access it
    # via the get_confirmation_callback dependency.
    from src.container import inject_confirmation_callback
    from src.infra.tools.confirmation import APIConfirmationCallback

    confirmation_callback = APIConfirmationCallback(
        timeout_seconds=60  # User has 60s to approve/deny before auto-deny
    )
    app.state.confirmation_callback = confirmation_callback
    inject_confirmation_callback(confirmation_callback)
    logger.info("HITL confirmation gate initialized (timeout=60s)")

    # Initialize Telegram Long Polling
    logger.info("Initializing Telegram Long Polling...")
    from src.api.routes.webhooks import _telegram

    await _telegram.start_polling()

    # Initialize and start APScheduler
    logger.info("Initializing background task scheduler...")

    from src.app.services.proactive_service import run_proactive_checks

    # Run proactive checks periodically (e.g. every 30 minutes)
    interval_minutes = settings.PROACTIVE_CHECK_INTERVAL_MINUTES
    scheduler.add_job(
        run_proactive_checks,
        "interval",
        minutes=interval_minutes,
        id="proactive_checks_job",
        replace_existing=True,
    )

    scheduler.start()

    # Initialize Autonomous Observation Loop
    logger.info("Initializing Autonomous Observation Loop...")
    from src.app.services.autonomous_loop import AutonomousObservationLoop

    observation_loop = AutonomousObservationLoop(
        interval_minutes=60, session_ids=["system_default_session"]
    )
    await observation_loop.start()

    logger.info(f"API ready at http://{settings.API_HOST}:{settings.API_PORT}")

    yield

    # Shutdown
    logger.info("Shutting down API...")
    if scheduler.running:
        scheduler.shutdown(wait=False)

    await _telegram.stop_polling()

    observation_loop.stop()

    # Clean up container resources (AmadeusService orchestrator, Redis, etc.)
    from src.container import shutdown_services

    await shutdown_services()

    await close_db()
    logger.info("Shutdown complete")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

from src.container import global_container


app = FastAPI(
    title=f"{settings.ASSISTANT_NAME} AI Assistant API",
    version=settings.ASSISTANT_VERSION,
    description="""
    RESTful API for the Amadeus AI Assistant.

    ## Features

    * **Tasks Management**: Create, list, complete, and delete tasks
    * **Notes**: Create, read, update, and delete notes with tagging
    * **Reminders**: Schedule and manage time-based reminders
    * **Calendar**: Manage calendar events and view agenda
    * **Voice**: Text-to-speech and speech-to-text processing
    * **System**: Monitor system health and status

    ## Authentication

    Currently in development mode with no authentication required.
    Production deployments should implement proper authentication.
    """,
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
app.add_middleware(AuditLoggerMiddleware)

# Rate limiting — per user (JWT sub) with IP fallback
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[f"{settings.RATE_LIMIT_REQUESTS}/minute"],
    storage_uri=settings.REDIS_URL if settings.REDIS_URL else None,
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
    logger.warning(f"Domain error: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)

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


@app.get("/sentry-debug", tags=["Health"])
async def trigger_error():
    division_by_zero = 1 / 0


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
    ipc,
    llm,
    messaging,
    system_admin,
    tasks,
    voice,
    webhooks,
    websocket,
)


# Disable auth for health + LLM usage, enable for everything else
app.include_router(health.router, prefix="/api/v1", tags=["System"])
app.include_router(llm.router, prefix="/api/v1", tags=["LLM"])  # No auth — informational

# Protected routes (Require basic User role)
protected_deps = [Depends(RequireUser)]
app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"], dependencies=protected_deps)
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"], dependencies=protected_deps)
app.include_router(voice.router, prefix="/api/v1", tags=["Voice"], dependencies=protected_deps)

# Admin only routes
app.include_router(system_admin.router, prefix="/api/v1", tags=["Admin System"])

# Webhooks use their own secret-token validation — no JWT
app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])


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

# WebSocket Endpoint (no HTTP prefix usually needed)
app.include_router(websocket.router, tags=["Realtime"])

# Inter-Process Communication (IPC) for localhost GUI System Tray
app.include_router(ipc.router, prefix="/api/v1", tags=["IPC"])

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
        "src.api.server:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
