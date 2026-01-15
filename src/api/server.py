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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.config import get_settings, validate_settings
from src.core.exceptions import AmadeusError
from src.infra.persistence.database import close_db, init_db


logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
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
    
    # Initialize database
    await init_db()
    
    logger.info(f"API ready at http://{settings.API_HOST}:{settings.API_PORT}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down API...")
    await close_db()
    logger.info("Shutdown complete")


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

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


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================

@app.exception_handler(AmadeusError)
async def amadeus_exception_handler(request: Request, exc: AmadeusError):
    """Handle domain-specific exceptions."""
    logger.warning(f"Domain error: {exc.message}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    
    if settings.DEBUG:
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
async def health_check():
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
async def root():
    """Root endpoint with API information."""
    return {
        "message": f"Welcome to {settings.ASSISTANT_NAME} API",
        "version": settings.ASSISTANT_VERSION,
        "docs": "/docs" if settings.DEBUG else "Disabled in production",
    }


# =============================================================================
# ROUTE REGISTRATION
# =============================================================================

# Import and register route modules
from src.api.routes import tasks, health  # noqa: E402

app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"])
app.include_router(health.router, prefix="/api/v1", tags=["System"])


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
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
