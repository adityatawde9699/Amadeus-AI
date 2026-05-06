"""
Dependency Injection Container for Amadeus AI.

Wires up all services with their dependencies using dependency-injector.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import redis.asyncio
from dependency_injector import containers, providers

from src.app.services.amadeus_service import AmadeusService
from src.app.services.tool_registry import ToolRegistry
from src.app.services.voice_service import VoiceService
from src.core.config import get_settings
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
        logger.exception("Failed to configure Redis client: %s", e)
        return None


def _build_cache_service(redis_client: redis.asyncio.Redis | None) -> CacheService:
    from src.infra.cache.cache_service import CacheService

    if not redis_client:
        logger.warning("Initializing CacheService in Local Zero-Dependency mode (in-memory dict).")
    return CacheService(redis=redis_client)


def _build_conversation_repo_factory() -> object:
    """Build a per-request conversation repository proxy.

    Returns a lightweight proxy that opens a fresh DB session for every
    repository method call, matching the _SessionProxy pattern used by
    the task/pomodoro tools.  This avoids holding a long-lived session
    inside the singleton AmadeusService.
    """
    from src.infra.persistence.database import get_session
    from src.infra.persistence.repositories.conversation_repository import (
        SQLConversationRepository,
    )

    class _ConversationRepoProxy:
        def __getattr__(self, method_name: str) -> object:
            async def _caller(*args: object, **kwargs: object) -> object:
                async with get_session() as session:
                    repo = SQLConversationRepository(session)
                    return await getattr(repo, method_name)(*args, **kwargs)

            return _caller

    return _ConversationRepoProxy()


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

        # Register developer/sandbox tools
        try:
            from src.infra.tools.developer_tools import get_developer_tools

            for tool in get_developer_tools():
                registry.register(tool)
        except Exception as e:
            logger.warning("Failed to register developer_tools: %s", e)

        # Register web_research and email tools (return plain dicts, not Tool objects)
        try:
            from src.infra.tools.base import ToolCategory
            from src.infra.tools.web_research_tools import build_web_research_tools

            for td in build_web_research_tools():
                registry.register_function(
                    func=td["function"],
                    name=td["name"],
                    description=td["description"],
                    category=ToolCategory.WEB_RESEARCH,
                    parameters=td.get("parameters", {}),
                )
        except Exception as e:
            logger.warning("Failed to register web_research_tools: %s", e)

        try:
            from src.infra.tools.base import ToolCategory
            from src.infra.tools.email_tools import build_email_tools

            for td in build_email_tools():
                registry.register_function(
                    func=td["function"],
                    name=td["name"],
                    description=td["description"],
                    category=ToolCategory.COMMUNICATION,
                    parameters=td.get("parameters", {}),
                    requires_confirmation=td["name"] == "send_email",  # sending is destructive
                )
        except Exception as e:
            logger.warning("Failed to register email_tools: %s", e)

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
        except Exception as e:
            logger.warning("Failed to configure GroqAdapter: %s", type(e).__name__)

    gemini_adapter = None
    if settings.GEMINI_API_KEY:
        try:
            from src.infra.llm.gemini_adapter import GeminiAdapter

            gemini_adapter = GeminiAdapter(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.warning("Failed to configure GeminiAdapter: %s", type(e).__name__)

    openai_adapter = None
    if getattr(settings, "OPENAI_API_KEY", None):
        try:
            from src.infra.llm.openai_adapter import OpenAIAdapter

            openai_adapter = OpenAIAdapter(api_key=settings.OPENAI_API_KEY)
        except Exception as e:
            logger.warning("Failed to configure OpenAIAdapter: %s", type(e).__name__)

    ollama_adapter = None
    # Only wire Ollama if explicitly enabled (avoids connection errors when not running)
    if getattr(settings, "OLLAMA_ENABLED", False):
        try:
            from src.infra.llm.ollama_adapter import OllamaAdapter

            ollama_adapter = OllamaAdapter(
                base_url=settings.OLLAMA_URL,
                model=settings.OLLAMA_MODEL,
                timeout=settings.OLLAMA_TIMEOUT_SECONDS,
                context_length=settings.OLLAMA_NUM_CTX,
            )
        except Exception as e:
            logger.warning("Failed to configure OllamaAdapter: %s", type(e).__name__)

    llama_cpp_adapter = None
    if getattr(settings, "SLM_MODEL_PATH", None):
        try:
            from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter

            llama_cpp_adapter = LlamaCppAdapter(
                model_path=settings.SLM_MODEL_PATH,
                threads=settings.SLM_THREADS,
                context_length=settings.SLM_CTX_SIZE,
            )
        except Exception as e:
            logger.exception("Failed to configure LlamaCppAdapter: %s", e)

    return LLMRouter(
        ollama=ollama_adapter,
        llama_cpp=llama_cpp_adapter,
        groq=groq_adapter,
        gemini=gemini_adapter,
        openai=openai_adapter,
        redis_url=getattr(settings, "REDIS_URL", None),
        local_only_mode=settings.LOCAL_ONLY_MODE,
    )


def _build_search_router() -> SearchRouter:
    from src.infra.search.search_router import SearchRouter

    settings = get_settings()
    return SearchRouter(
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

    conversation_repo = providers.Singleton(_build_conversation_repo_factory)

    # llm_router and search_router must be declared BEFORE amadeus_service
    # so dependency-injector can resolve them as constructor arguments.
    llm_router = providers.Singleton(_build_llm_router)
    search_router = providers.Singleton(_build_search_router)

    amadeus_service = providers.Singleton(
        AmadeusService,
        settings=settings,
        tool_registry=tool_registry,
        cache_service=cache_service,
        conversation_repo=conversation_repo,
        llm_router=llm_router,
    )

    voice_service = providers.Singleton(
        _build_voice_service,
        amadeus=amadeus_service,
        cache=cache_service,
    )


# =============================================================================
# GLOBAL BRIDGES (Backward Compatibility)
# =============================================================================


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


async def shutdown_services() -> None:
    """Clean up container resources on shutdown."""
    logger.info("Shutting down resources...")

    # Cleanly cancel the AgentOrchestrator background worker
    try:
        amadeus = global_container.amadeus_service()
        await amadeus.shutdown()
    except Exception:
        logger.debug("AmadeusService shutdown skipped (not initialized)")

    redis_cli = global_container.redis_client()
    if redis_cli:
        await redis_cli.aclose()

    global_container.shutdown_resources()
    logger.info("Dependencies shut down complete")


global_container = Container()
