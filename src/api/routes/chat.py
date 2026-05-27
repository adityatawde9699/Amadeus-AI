"""
Chat API Routes for Amadeus AI.

Provides the main /chat endpoint for processing user requests,
plus a server-sent events (SSE) streaming endpoint for lower TTFT.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth.manager import current_active_user, fastapi_users
from src.infra.persistence.orm_models import UserORM


optional_user = fastapi_users.current_user(active=True, optional=True)
from dependency_injector.wiring import Provide, inject

from src.app.services.agent_loop import QueueFullError
from src.app.services.amadeus_service import AmadeusService
from src.container import Container
from src.core.domain.models import (
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    MessageResponse,
    PermissionProfile,
    ToolListResponse,
)
from src.infra.persistence.database import get_db_session
from src.infra.persistence.repositories.conversation_repository import SQLConversationRepository


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])

# Limit concurrent chat requests to prevent event-loop saturation / DoS.
_MAX_CONCURRENT_CHATS = 5
_chat_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CHATS)


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post("", response_model=ChatResponse)
@inject
async def chat(
    request: ChatRequest,
    amadeus: AmadeusService = Depends(Provide[Container.amadeus_service]),
    user: UserORM | None = Depends(optional_user),
) -> ChatResponse:
    """
    Main chat endpoint.

    Processes user messages through the Amadeus AI assistant,
    using ML-based tool selection to optimize API usage.
    """
    try:
        async with _chat_semaphore:
            active_session_id = (
                str(user.id) if user is not None else request.session_id or amadeus.session_id
            )

            # Extract Permission Profile
            profile = PermissionProfile.SYSTEM_FULL
            if user is not None and user.role.value.lower() == "guest":
                profile = PermissionProfile.READ_ONLY

            try:
                response = await amadeus.handle_command(
                    user_input=request.message,
                    source=request.source,
                    request_id=request.request_id,
                    session_id=active_session_id,
                    permission_profile=profile,
                )
            except QueueFullError as e:
                raise HTTPException(status_code=429, detail=str(e)) from e

        return ChatResponse(
            response=response,
            source=request.source,
            session_id=active_session_id,
            tools_used=[],
        )

    except HTTPException:
        raise  # Re-raise known HTTP errors (503 above) unchanged
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    session_id: str = Query(..., description="Session ID to get history for"),
    user: UserORM = Depends(current_active_user),
) -> HistoryResponse:
    """
    Get conversation history for a session.

    Returns all messages from the specified session.
    """
    try:
        if session_id != str(user.id):
            raise HTTPException(status_code=403, detail="Forbidden")

        async for session in get_db_session():
            repo = SQLConversationRepository(session)
            messages = await repo.get_session_history(session_id)
            return HistoryResponse(
                session_id=session_id,
                messages=[MessageResponse(**m) for m in messages],
                total=len(messages),
            )
        # Session generator yielded nothing — should not happen in practice
        raise HTTPException(status_code=500, detail="Database session unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("History error: %s", e, exc_info=True)
        # CQ-07: Never expose raw exception messages to clients (may leak DB schema / paths).
        raise HTTPException(status_code=500, detail="An internal error occurred") from e


@router.get("/tools", response_model=ToolListResponse)
@inject
async def list_tools(
    amadeus: AmadeusService = Depends(Provide[Container.amadeus_service]),
) -> ToolListResponse:
    """
    List all available tools.

    Returns tool names organized by category.
    """
    summary = amadeus.get_tool_summary()
    return ToolListResponse(
        total=summary["total"],
        categories=summary["categories"],
    )


@router.post("/clear")
@inject
async def clear_conversation(
    amadeus: AmadeusService = Depends(Provide[Container.amadeus_service]),
) -> dict[str, str]:
    """
    Clear conversation history (cache and database).
    """
    await amadeus.clear_conversation()
    return {"status": "ok", "message": "Conversation cleared"}



