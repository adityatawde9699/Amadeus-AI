"""
Dependency Injection Container for Amadeus AI.

Wires up all services with their dependencies using dependency-injector.
For simplicity, this module provides factory functions that can be used
directly or with a DI framework.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import TYPE_CHECKING

from src.app.services.amadeus_service import AmadeusService
from src.app.services.tool_registry import ToolRegistry
from src.core.config import get_settings

if TYPE_CHECKING:
    import redis.asyncio
    from src.infra.cache.cache_service import CacheService
    from src.infra.llm.router import LLMRouter
    from src.infra.search.search_router import SearchRouter
    from src.infra.tools.confirmation import ConfirmationCallback
    from src.app.services.voice_service import VoiceService


logger = logging.getLogger(__name__)


# =============================================================================
# CACHED SINGLETONS
# =============================================================================

@lru_cache
def get_tool_registry() -> ToolRegistry:
    """
    Get the tool registry singleton.

    Phase 3: Task and Pomodoro tools are constructed with injected repositories.
    Note: SQLAlchemyTaskRepository and SQLAlchemyPomodoroRepository are initialized
    once at startup; they do NOT hold a long-lived session — they receive a new
    session per call via the parent context manager in their usage paths.
    Legacy tools (note, reminder) still use _get_session() internally.
    """
    registry = ToolRegistry()

    # ── Repository-injected tools ─────────────────────────────────────────────
    try:
        from src.infra.persistence.database import get_session
        from src.infra.persistence.repositories.pomodoro_repository import (
            SQLAlchemyPomodoroRepository,
        )
        from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository
        from src.infra.tools.productivity_tools import build_pomodoro_tools, build_task_tools

        # We create thin ``SessionProxy`` wrappers that open a fresh session per call.
        # This avoids holding a long-lived session in the singleton.
        class _SessionProxy:
            """Thin wrapper to give repository factories a lazy session per call."""
            def __init__(self, repo_cls: type) -> None:
                self._repo_cls = repo_cls

            def __getattr__(self, method_name: str) -> object:
                async def _caller(*args: object, **kwargs: object) -> object:
                    async with get_session() as session:
                        repo = self._repo_cls(session)
                        return await getattr(repo, method_name)(*args, **kwargs)
                return _caller

        task_repo = _SessionProxy(SQLAlchemyTaskRepository)
        pomodoro_repo = _SessionProxy(SQLAlchemyPomodoroRepository)

        for t in build_task_tools(task_repo):       # type: ignore[arg-type]
            registry.register(t)
        for t in build_pomodoro_tools(pomodoro_repo):  # type: ignore[arg-type]
            registry.register(t)

        logger.info("Registered repository-injected tools (task, pomodoro)")
    except Exception as e:
        logger.exception("Error registering injected tools: %s", e)

    # ── Auto-discovered tools (info, system, monitor, legacy productivity) ────
    try:
        from src.infra.tools.filesystem_tools import build_filesystem_tools
        from src.infra.tools.info_tools import get_info_tools
        from src.infra.tools.monitor_tools import get_monitor_tools
        from src.infra.tools.productivity_tools import get_productivity_tools
        from src.infra.tools.system_tools import get_system_tools

        for tool in get_info_tools():
            registry.register(tool)
        for tool in get_system_tools():
            registry.register(tool)
        for tool in get_monitor_tools():
            registry.register(tool)
        for tool in get_productivity_tools():
            registry.register(tool)
        for tool in build_filesystem_tools():
            registry.register(tool)

        logger.info("Tool registry initialized with %d tools", len(registry))
    except Exception as e:
        logger.exception("Error initializing tool registry: %s", e)

    return registry


@lru_cache
def get_amadeus_service() -> AmadeusService:
    """
    Get the Amadeus service singleton.

    This is the main orchestrator with ML classifier for tool selection.

    Note: The ToolExecutor inside this service is constructed WITHOUT a
    ConfirmationCallback by default. When served via the FastAPI app, the
    callback singleton from ``app.state`` is injected at request-time by
    calling ``inject_confirmation_callback()``. This keeps the container
    framework-agnostic.
    """
    settings = get_settings()
    registry = get_tool_registry()
    cache_service = get_cache_service()

    service = AmadeusService(
        settings=settings,
        tool_registry=registry,
        cache_service=cache_service,
    )

    logger.info("AmadeusService singleton initialized")
    return service


def inject_confirmation_callback(confirmation_callback: ConfirmationCallback) -> None:
    """
    Inject the HITL ``ConfirmationCallback`` into the AmadeusService's
    ToolExecutor after the FastAPI app has started.

    Called once during the lifespan startup sequence, after both the
    ``APIConfirmationCallback`` singleton and the ``AmadeusService``
    singleton have been created.

    This pattern avoids importing FastAPI's ``app.state`` in the container,
    keeping the container fully framework-agnostic.
    """
    service = get_amadeus_service()
    service.tool_executor.confirmation_callback = confirmation_callback
    logger.info(
        "ConfirmationCallback injected into ToolExecutor (%s)",
        type(confirmation_callback).__name__,
    )


@lru_cache
def get_llm_router() -> "LLMRouter":
    """
    Get the LLM Router singleton.

    Chains: Groq (free, 14.4K/day) → Gemini (free, 1.5K/day) → OpenAI (paid, emergency)
    Daily usage counters are stored in Redis when available (multi-worker safe),
    falling back to in-memory counters for single-instance deployments.
    """
    from src.infra.llm.gemini_adapter import GeminiAdapter
    from src.infra.llm.router import LLMRouter

    settings = get_settings()

    groq_adapter = None
    if settings.GROQ_API_KEY:
        try:
            from src.infra.llm.groq_adapter import GroqAdapter
            groq_adapter = GroqAdapter(api_key=settings.GROQ_API_KEY)
            logger.info("Groq adapter configured as primary LLM")
        except Exception as e:
            logger.warning("Failed to configure Groq adapter: %s", e)

    gemini_adapter = None
    if settings.GEMINI_API_KEY:
        try:
            gemini_adapter = GeminiAdapter(api_key=settings.GEMINI_API_KEY)
            logger.info("Gemini adapter configured as secondary LLM")
        except Exception as e:
            logger.warning("Failed to configure Gemini adapter: %s", e)

    openai_adapter = None
    if getattr(settings, "OPENAI_API_KEY", None):
        try:
            from src.infra.llm.openai_adapter import OpenAIAdapter
            openai_adapter = OpenAIAdapter(api_key=settings.OPENAI_API_KEY)
            logger.info("OpenAI adapter configured as emergency fallback LLM")
        except Exception as e:
            logger.warning("Failed to configure OpenAI adapter: %s", e)

    # Pass Redis URL so LLMRouter can use shared counters in multi-worker deployments
    redis_url = getattr(settings, "REDIS_URL", None)

    router = LLMRouter(
        groq=groq_adapter,
        gemini=gemini_adapter,
        openai=openai_adapter,
        redis_url=redis_url,
    )
    active = [k for k, v in {"groq": groq_adapter, "gemini": gemini_adapter, "openai": openai_adapter}.items() if v]
    logger.info("LLMRouter initialized with providers: %s", active)
    return router


# =============================================================================
# ASYNC SESSION FACTORY
# =============================================================================

async def get_db_session() -> AsyncGenerator:
    """
    FastAPI dependency for database sessions.

    Usage in routes:
        @router.get("/tasks")
        async def list_tasks(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    from src.infra.persistence.database import get_session
    async with get_session() as session:
        yield session


# =============================================================================
# VOICE SERVICE INJECTION
# =============================================================================

@lru_cache
def get_voice_service() -> "VoiceService":
    """
    Get the Voice Service singleton.
    Uses EdgeTTS (free, unlimited) as the primary TTS provider.
    """
    from src.app.services.voice_service import VoiceService
    from src.infra.speech.adapters import WhisperVoiceInput

    amadeus = get_amadeus_service()
    settings = get_settings()
    stt = WhisperVoiceInput()

    # Build TTS router: EdgeTTS only
    try:
        from src.infra.speech.edge_tts_adapter import EdgeTTSAdapter
        from src.infra.speech.tts_router import TTSRouter
        cache_service = get_cache_service()
        edge_tts = EdgeTTSAdapter(voice=settings.EDGE_TTS_VOICE, cache_service=cache_service)
        tts = TTSRouter(edge_tts=edge_tts)
        logger.info("TTSRouter initialized (EdgeTTS only - $0/month)")
    except ImportError:
        # Fallback: edge-tts not installed, use silent adapter
        logger.warning("edge-tts not installed, TTS will return empty bytes. Install: pip install edge-tts")
        from src.infra.speech.adapters import _SilentTTSAdapter
        tts = _SilentTTSAdapter()  # type: ignore[assignment]

    service = VoiceService(
        amadeus_service=amadeus,
        stt_service=stt,
        tts_service=tts,
    )
    logger.info("VoiceService singleton initialized")
    return service


# =============================================================================
# CACHE CLIENT
# =============================================================================

@lru_cache
def get_redis_client() -> "redis.asyncio.Redis | None":
    """
    Get the Redis cache client singleton.

    Returns None if redis connection fails or is not configured properly.
    """
    import redis.asyncio as redis
    settings = get_settings()

    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=False) # Wait, cache service expects bytes for tts? Actually it gets decoded in CacheService based on isinstance(bytes). Actually decode_responses=False is safer for bytes.
        logger.info("Redis cache client configured")
        return client
    except Exception as e:
        logger.exception(f"Failed to configure Redis client: {e}")
        return None

@lru_cache
def get_cache_service() -> "CacheService":
    """
    Get the CacheService singleton.
    Provides Redis-backed caching for LLM, TTS, tools, and search.
    Falls back gracefully to an in-memory dictionary if Redis is unavailable.
    """
    from src.infra.cache.cache_service import CacheService
    redis_client = get_redis_client()
    if not redis_client:
        logger.warning("Initializing CacheService in Local Zero-Dependency mode (in-memory dict).")
    return CacheService(redis=redis_client)


# =============================================================================
# SEARCH ROUTER
# =============================================================================

@lru_cache
def get_search_router() -> "SearchRouter":
    """
    Get the SearchRouter singleton.

    Routing order (cost-optimised, free-first):
      1. DuckDuckGo Instant Answer API  — always free, no key
      2. Brave Search API               — 2 000 req/month free (key optional)
      3. Tavily Search API              — deep/AI search, paid (key optional)
    """
    from src.infra.search.search_router import SearchRouter
    settings = get_settings()
    router = SearchRouter(
        brave_api_key=getattr(settings, "BRAVE_SEARCH_API_KEY", None),
        tavily_api_key=getattr(settings, "TAVILY_API_KEY", None),
    )
    logger.info(
        "SearchRouter initialised — Brave=%s, Tavily=%s",
        bool(getattr(settings, "BRAVE_SEARCH_API_KEY", None)),
        bool(getattr(settings, "TAVILY_API_KEY", None)),
    )
    return router


async def shutdown_services() -> None:
    """
    Clean up all services on application shutdown.
    """
    logger.info("Shutting down services...")

    # Clear cached instances
    get_tool_registry.cache_clear()
    get_amadeus_service.cache_clear()
    get_voice_service.cache_clear()
    get_llm_router.cache_clear()
    get_search_router.cache_clear()

    # Close Redis connection if active
    redis_client = get_redis_client()
    if redis_client:
        await redis_client.aclose()
    get_redis_client.cache_clear()

    logger.info("Services shut down complete")



