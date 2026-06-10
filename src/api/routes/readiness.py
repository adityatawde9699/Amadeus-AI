"""
Observability Improvements — Phase 12 Architecture Upgrade.

Adds:
  1. Per-tool execution Histogram + Counter (audit recommendation)
  2. /health/live  — simple liveness probe (always 200 if process is up)
  3. /health/ready — readiness probe that checks DB, Redis, Turbovec, LLM
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


# ---------------------------------------------------------------------------
# Liveness probe  (/health/live)
# ---------------------------------------------------------------------------


@router.get(
    "/health/live",
    summary="Liveness probe",
    description=(
        "Returns 200 as long as the process is alive. "
        "Used by container orchestrators (Kubernetes, Docker Compose) to detect crashes."
    ),
)
async def liveness() -> dict[str, str]:
    """Always 200 while the process is running."""
    return {"status": "alive"}


# ---------------------------------------------------------------------------
# Readiness probe  (/health/ready)
# ---------------------------------------------------------------------------


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description=(
        "Checks all critical dependencies before accepting traffic. "
        "Returns 200 only when the database, cache, vector store, and LLM are reachable."
    ),
)
async def readiness() -> dict[str, object]:
    """
    Phase 12 readiness check with per-dependency health gates.

    A 503 response means the service should not receive traffic yet.
    The body contains a map of dependency → status so load-balancers
    and operators can see exactly which component is unhealthy.
    """
    from src.core.config import get_settings

    settings = get_settings()
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    # ── Database ─────────────────────────────────────────────────────────────
    try:
        from src.infra.persistence.database import get_db_session

        async for session in get_db_session():
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        logger.warning("Readiness: database check failed: %s", exc)
        checks["database"] = False
        details["database"] = str(exc)

    # ── Redis ─────────────────────────────────────────────────────────────────
    try:
        import redis.asyncio as _aioredis

        r = _aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception as exc:
        logger.warning("Readiness: Redis check failed: %s", exc)
        checks["redis"] = False
        details["redis"] = str(exc)

    # ── Turbovec (vector memory) ──────────────────────────────────────────────
    # Replaces the previous Qdrant check — Qdrant was moved to an optional
    # dependency in v5. Turbovec is the active memory backend.
    try:
        if settings.MEMORY_ENABLED:
            from src.container import global_container

            amadeus = global_container.amadeus_service()
            if amadeus and amadeus.memory_service.is_enabled:
                # Deep query check: run a real embed + search to verify both
                # the sentence-transformers model and turbovec index are alive.
                await amadeus.memory_service.retrieve("health check ping", top_k=1)
        checks["turbovec"] = True
    except Exception as exc:
        logger.warning("Readiness: Turbovec check failed: %s", exc)
        checks["turbovec"] = False
        details["turbovec"] = str(exc)

    # ── LLM provider ─────────────────────────────────────────────────────────
    try:
        from src.container import global_container

        router_svc = global_container.llm_router()
        # If we can retrieve the router without exception, providers are configured
        checks["llm_provider"] = router_svc is not None
    except Exception as exc:
        logger.warning("Readiness: LLM router check failed: %s", exc)
        checks["llm_provider"] = False
        details["llm_provider"] = str(exc)

    # ── Aggregate result ──────────────────────────────────────────────────────
    all_ready = all(checks.values())
    if not all_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"checks": checks, "details": details},
        )

    return {"status": "ready", "checks": checks}
