"""
Dependency Injection Container for Amadeus AI.

Wires up all services with their dependencies using dependency-injector.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dependency_injector import containers, providers

from src.app.services.amadeus_service import AmadeusService
from src.app.services.tool_registry import ToolRegistry
from src.core.config import get_settings


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from concurrent.futures import ThreadPoolExecutor

    import redis.asyncio

    from src.app.services.voice_service import VoiceService
    from src.infra.cache.cache_service import CacheService
    from src.infra.llm.router import LLMRouter
    from src.infra.search.search_router import SearchRouter
    from src.infra.tools.confirmation import ConfirmationCallback

logger = logging.getLogger(__name__)


# ── Builders and Factories (logic preserved to avoid circular imports) ────────


def _build_redis_client() -> redis.asyncio.Redis | None:
    import redis.asyncio as redis

    settings = get_settings()
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=False)
        logger.info("Redis cache client configured via container")
        return client
    except Exception as e:
        logger.exception(f"Failed to configure Redis client: {e}")
        return None


def _build_cache_service(redis_client: redis.asyncio.Redis | None) -> CacheService:
    from src.infra.cache.cache_service import CacheService

    if not redis_client:
        logger.warning("Initializing CacheService in Local Zero-Dependency mode (in-memory dict).")
    return CacheService(redis=redis_client)


def _build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    try:
        from src.infra.persistence.database import get_session
        from src.infra.persistence.repositories.pomodoro_repository import (
            SQLAlchemyPomodoroRepository,
        )
        from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository
        from src.infra.tools.productivity_tools import build_pomodoro_tools, build_task_tools

        class _SessionProxy:
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

        for t in build_task_tools(task_repo):  # type: ignore[arg-type]
            registry.register(t)
        for t in build_pomodoro_tools(pomodoro_repo):  # type: ignore[arg-type]
            registry.register(t)
        logger.info("Registered repository-injected tools (task, pomodoro)")
    except Exception as e:
        logger.exception("Error registering injected tools: %s", e)

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


def _build_llm_router() -> LLMRouter:
    from src.infra.llm.gemini_adapter import GeminiAdapter
    from src.infra.llm.router import LLMRouter

    settings = get_settings()

    groq_adapter = None
    if settings.GROQ_API_KEY:
        try:
            from src.infra.llm.groq_adapter import GroqAdapter

            groq_adapter = GroqAdapter(api_key=settings.GROQ_API_KEY)
        except Exception:
            pass

    gemini_adapter = None
    if settings.GEMINI_API_KEY:
        try:
            from src.infra.llm.gemini_adapter import GeminiAdapter

            gemini_adapter = GeminiAdapter(api_key=settings.GEMINI_API_KEY)
        except Exception:
            pass

    openai_adapter = None
    if getattr(settings, "OPENAI_API_KEY", None):
        try:
            from src.infra.llm.openai_adapter import OpenAIAdapter

            openai_adapter = OpenAIAdapter(api_key=settings.OPENAI_API_KEY)
        except Exception:
            pass

    return LLMRouter(
        groq=groq_adapter,
        gemini=gemini_adapter,
        openai=openai_adapter,
        redis_url=getattr(settings, "REDIS_URL", None),
    )


def _build_search_router() -> SearchRouter:
    from src.infra.search.search_router import SearchRouter

    settings = get_settings()
    return SearchRouter(
        brave_api_key=getattr(settings, "BRAVE_SEARCH_API_KEY", None),
        tavily_api_key=getattr(settings, "TAVILY_API_KEY", None),
    )


def _build_voice_service(amadeus: AmadeusService, cache: CacheService) -> VoiceService:
    from src.app.services.voice_service import VoiceService
    from src.infra.speech.adapters import WhisperVoiceInput

    settings = get_settings()
    stt = WhisperVoiceInput()
    try:
        from src.infra.speech.edge_tts_adapter import EdgeTTSAdapter
        from src.infra.speech.tts_router import TTSRouter

        edge_tts = EdgeTTSAdapter(voice=settings.EDGE_TTS_VOICE, cache_service=cache)
        tts = TTSRouter(edge_tts=edge_tts)
    except ImportError:
        from src.infra.speech.adapters import _SilentTTSAdapter

        tts = _SilentTTSAdapter()  # type: ignore[assignment]

    return VoiceService(amadeus_service=amadeus, stt_service=stt, tts_service=tts)


def _build_ml_thread_pool() -> ThreadPoolExecutor:
    from concurrent.futures import ThreadPoolExecutor

    # A dedicated single-worker pool perfectly bypasses OOM issues on concurrent voice requests
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="VoiceML")


# =============================================================================
# DEPENDENCY INJECTOR CONTAINER
# =============================================================================


class Container(containers.DeclarativeContainer):
    """IoC container of application dependencies."""

    wiring_config = containers.WiringConfiguration(
        modules=[
            "src.api.routes.chat",
            "src.api.routes.confirm",
            "src.api.routes.health",
            "src.api.routes.ipc",
            "src.api.routes.llm",
            "src.api.routes.messaging",
            "src.api.routes.system_admin",
            "src.api.routes.tasks",
            "src.api.routes.voice",
            "src.api.routes.webhooks",
            "src.api.routes.websocket",
        ]
    )

    config = providers.Configuration()
    settings = providers.Factory(get_settings)

    ml_thread_pool = providers.Singleton(_build_ml_thread_pool)

    redis_client = providers.Singleton(_build_redis_client)
    cache_service = providers.Singleton(_build_cache_service, redis_client=redis_client)

    tool_registry = providers.Singleton(_build_tool_registry)

    amadeus_service = providers.Singleton(
        AmadeusService,
        settings=settings,
        tool_registry=tool_registry,
        cache_service=cache_service,
    )

    llm_router = providers.Singleton(_build_llm_router)
    search_router = providers.Singleton(_build_search_router)

    voice_service = providers.Singleton(
        _build_voice_service,
        amadeus=amadeus_service,
        cache=cache_service,
    )


# =============================================================================
# GLOBAL BRIDGES (Backward Compatibility)
# =============================================================================

global_container = Container()


def get_amadeus_service() -> AmadeusService:
    return global_container.amadeus_service()


def get_tool_registry() -> ToolRegistry:
    return global_container.tool_registry()


def get_redis_client() -> redis.asyncio.Redis | None:
    return global_container.redis_client()


def get_cache_service() -> CacheService:
    return global_container.cache_service()


def get_voice_service() -> VoiceService:
    return global_container.voice_service()


def get_llm_router() -> LLMRouter:
    return global_container.llm_router()


def get_search_router() -> SearchRouter:
    return global_container.search_router()


def inject_confirmation_callback(confirmation_callback: ConfirmationCallback) -> None:
    service = get_amadeus_service()
    service.tool_executor.confirmation_callback = confirmation_callback
    logger.info("ConfirmationCallback injected into ToolExecutor")


async def get_db_session() -> AsyncGenerator:
    """FastAPI dependency for DB sessions."""
    from src.infra.persistence.database import get_session

    async with get_session() as session:
        yield session


async def shutdown_services() -> None:
    """Clean up container resources on shutdown."""
    logger.info("Shutting down resources...")
    redis_cli = global_container.redis_client()
    if redis_cli:
        await redis_cli.aclose()

    global_container.shutdown_resources()
    logger.info("Dependencies shut down complete")
