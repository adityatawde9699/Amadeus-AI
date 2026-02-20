"""
Chat API Routes for Amadeus AI.

Provides the main /chat endpoint for processing user requests.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from src.container import get_amadeus_service, get_db_session
from src.app.services.amadeus_service import AmadeusService
from src.infra.persistence.repositories.conversation_repository import SQLConversationRepository
from src.core.domain.models import ChatRequest, ChatResponse, ToolListResponse, MessageResponse, HistoryResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    amadeus: AmadeusService = Depends(get_amadeus_service),
) -> ChatResponse:
    """
    Main chat endpoint.
    
    Processes user messages through the Amadeus AI assistant,
    using ML-based tool selection to optimize API usage.
    """
    try:
        # Use provided session_id or create new one from service
        if request.session_id:
            amadeus.session_id = request.session_id
        
        response = await amadeus.handle_command(
            user_input=request.message,
            source=request.source,
            request_id=request.request_id,
        )
        
        return ChatResponse(
            response=response,
            source=request.source,
            session_id=amadeus.session_id,
            tools_used=[],
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    session_id: str = Query(..., description="Session ID to get history for"),
) -> HistoryResponse:
    """
    Get conversation history for a session.
    
    Returns all messages from the specified session.
    """
    try:
        async for session in get_db_session():
            repo = SQLConversationRepository(session)
            messages = await repo.get_session_history(session_id)
            return HistoryResponse(
                session_id=session_id,
                messages=[MessageResponse(**m) for m in messages],
                total=len(messages),
            )
    except Exception as e:
        logger.error(f"History error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    amadeus: AmadeusService = Depends(get_amadeus_service),
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
async def clear_conversation(
    amadeus: AmadeusService = Depends(get_amadeus_service),
) -> dict[str, str]:
    """
    Clear conversation history (cache and database).
    """
    await amadeus.clear_conversation()
    return {"status": "ok", "message": "Conversation cleared"}

