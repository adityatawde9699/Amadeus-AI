"""
Dependency Injection Container for Amadeus AI.

Wires up all services with their dependencies using dependency-injector.
For simplicity, this module provides factory functions that can be used
directly or with a DI framework.
"""

import logging
from functools import lru_cache
from typing import AsyncGenerator

from src.core.config import Settings, get_settings
from src.app.services.tool_registry import ToolRegistry
from src.app.services.amadeus_service import AmadeusService


logger = logging.getLogger(__name__)


# =============================================================================
# CACHED SINGLETONS
# =============================================================================

@lru_cache()
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
        from src.infra.persistence.repositories.task_repository import SQLAlchemyTaskRepository
        from src.infra.persistence.repositories.pomodoro_repository import SQLAlchemyPomodoroRepository
        from src.infra.tools.productivity_tools import build_task_tools, build_pomodoro_tools

        # We create thin ``SessionProxy`` wrappers that open a fresh session per call.
        # This avoids holding a long-lived session in the singleton.
        class _SessionProxy:
            """Thin wrapper to give repository factories a lazy session per call."""
            def __init__(self, repo_cls):
                self._repo_cls = repo_cls

            def __getattr__(self, method_name):
                async def _caller(*args, **kwargs):
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
        logger.error("Error registering injected tools: %s", e)

    # ── Auto-discovered tools (info, system, monitor, legacy productivity) ────
    try:
        from src.infra.tools.info_tools import get_info_tools
        from src.infra.tools.system_tools import get_system_tools
        from src.infra.tools.monitor_tools import get_monitor_tools
        from src.infra.tools.productivity_tools import get_productivity_tools

        for tool in get_info_tools():
            registry.register(tool)
        for tool in get_system_tools():
            registry.register(tool)
        for tool in get_monitor_tools():
            registry.register(tool)
        for tool in get_productivity_tools():
            registry.register(tool)

        logger.info("Tool registry initialized with %d tools", len(registry))
    except Exception as e:
        logger.error("Error initializing tool registry: %s", e)

    return registry


@lru_cache()
def get_amadeus_service() -> AmadeusService:
    """
    Get the Amadeus service singleton.
    
    This is the main orchestrator with ML classifier for tool selection.
    """
    settings = get_settings()
    registry = get_tool_registry()
    
    service = AmadeusService(
        settings=settings,
        tool_registry=registry,
    )
    
    logger.info("AmadeusService singleton initialized")
    return service


@lru_cache()
def get_llm_router() -> "LLMRouter":
    """
    Get the LLM Router singleton.

    Chains: Groq (free, 14.4K/day) → Gemini (free, 1.5K/day) → OpenAI (paid, emergency)
    """
    from src.infra.llm.router import LLMRouter
    from src.infra.llm.gemini_adapter import GeminiAdapter

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

    router = LLMRouter(groq=groq_adapter, gemini=gemini_adapter)
    logger.info(
        "LLMRouter initialized with providers: %s",
        [k for k, v in {"groq": groq_adapter, "gemini": gemini_adapter}.items() if v]
    )
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

@lru_cache()
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
    
    # Build TTS router: EdgeTTS (default) + ElevenLabs (critical priority)
    try:
        from src.infra.speech.edge_tts_adapter import EdgeTTSAdapter
        from src.infra.speech.tts_router import TTSRouter
        edge_tts = EdgeTTSAdapter(voice=settings.EDGE_TTS_VOICE)
        
        elevenlabs_adapter = None
        if settings.ELEVENLABS_API_KEY:
            try:
                from src.infra.speech.tts_router import ElevenLabsAdapter
                elevenlabs_adapter = ElevenLabsAdapter(api_key=settings.ELEVENLABS_API_KEY)
            except Exception as e:
                logger.warning("ElevenLabs TTS unavailable: %s", e)
        
        tts = TTSRouter(edge_tts=edge_tts, elevenlabs=elevenlabs_adapter)
        logger.info("TTSRouter initialized (EdgeTTS primary)")
    except ImportError:
        # Fallback: edge-tts not installed, use silent adapter
        logger.warning("edge-tts not installed, TTS will return empty bytes. Install: pip install edge-tts")
        from src.infra.speech.adapters import _SilentTTSAdapter  # type: ignore[attr-defined]
        tts = _SilentTTSAdapter()
    
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

@lru_cache()
def get_redis_client() -> "redis.asyncio.Redis | None":
    """
    Get the Redis cache client singleton.
    
    Returns None if redis connection fails or is not configured properly.
    """
    import redis.asyncio as redis
    settings = get_settings()
    
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        logger.info("Redis cache client configured")
        return client
    except Exception as e:
        logger.error(f"Failed to configure Redis client: {e}")
        return None

# =============================================================================
# CLEANUP
# =============================================================================

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
    
    # Close Redis connection if active
    redis_client = get_redis_client()
    if redis_client:
        await redis_client.aclose()
    get_redis_client.cache_clear()
    
    logger.info("Services shut down complete")



