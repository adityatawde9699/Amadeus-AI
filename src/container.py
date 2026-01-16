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
    
    Tools are registered on first call.
    """
    registry = ToolRegistry()
    
    # Auto-discover and register all tools
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
        
        logger.info(f"Tool registry initialized with {len(registry)} tools")
    except Exception as e:
        logger.error(f"Error initializing tool registry: {e}")
    
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
    
    logger.info("Services shut down complete")

