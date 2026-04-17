"""
Chat API Routes for Amadeus AI.

Provides the main /chat endpoint for processing user requests,
plus a server-sent events (SSE) streaming endpoint for lower TTFT.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.auth.manager import fastapi_users
from src.infra.persistence.orm_models import UserORM


optional_user = fastapi_users.current_user(active=True, optional=True)
from dependency_injector.wiring import Provide, inject

from src.app.services.agent_loop import QueueFullError
from src.app.services.amadeus_service import AmadeusService
from src.container import Container
from src.infra.persistence.database import get_db_session
from src.core.domain.models import (
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    MessageResponse,
    PermissionProfile,
    ToolListResponse,
)
from src.infra.persistence.repositories.conversation_repository import SQLConversationRepository


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])

# Limit concurrent chat requests to prevent event-loop saturation / DoS.
# Callers that exceed this receive HTTP 503 rather than queuing indefinitely.
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
        # Guard against too many simultaneous in-flight requests
        if _chat_semaphore.locked():
            raise HTTPException(
                status_code=503, detail="Server busy — too many concurrent requests. Please retry."
            )

        async with _chat_semaphore:
            # Use provided session_id or create new one from service
            if request.session_id:
                amadeus.session_id = request.session_id

            # Extract Permission Profile
            profile = PermissionProfile.SYSTEM_FULL
            if user is not None and user.role.value.lower() == "guest":
                profile = PermissionProfile.READ_ONLY

            try:
                response = await amadeus.handle_command(
                    user_input=request.message,
                    source=request.source,
                    request_id=request.request_id,
                    permission_profile=profile,
                )
            except QueueFullError as e:
                raise HTTPException(status_code=429, detail=str(e))

        return ChatResponse(
            response=response,
            source=request.source,
            session_id=amadeus.session_id,
            tools_used=[],
        )

    except HTTPException:
        raise  # Re-raise known HTTP errors (503 above) unchanged
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred")


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
        # Session generator yielded nothing — should not happen in practice
        raise HTTPException(status_code=500, detail="Database session unavailable")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"History error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get(
    "/stream",
    summary="Stream a chat response via Server-Sent Events (SSE)",
    response_class=StreamingResponse,
)
@inject
async def chat_stream(
    message: str = Query(..., description="User message to send to Amadeus"),
    session_id: str | None = Query(default=None, description="Optional session ID for context"),
    source: str = Query(default="api", description="Request source identifier"),
    amadeus: AmadeusService = Depends(Provide[Container.amadeus_service]),
    user: UserORM | None = Depends(optional_user),
) -> StreamingResponse:
    """
    Stream the Amadeus response as Server-Sent Events (SSE).

    Uses Gemini ``stream=True`` when available; falls back to word-by-word
    chunking for Groq so the client always sees progressive output.

    **SSE event format**::

        data: {"delta": "token text"}

        data: [DONE]
    """
    if session_id:
        amadeus.session_id = session_id

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # --- Native Gemini streaming (lowest TTFT) ---
            gemini_model = getattr(amadeus, "model", None)
            if gemini_model is not None:
                try:
                    system_prompt = getattr(amadeus, "_get_system_prompt", lambda: "")() or ""
                    full_prompt = f"{system_prompt}\n\nUser: {message}\nAssistant:"
                    stream = gemini_model.generate_content(full_prompt, stream=True)
                    for chunk in stream:
                        if chunk.text:
                            yield f"data: {json.dumps({'delta': chunk.text})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                except Exception as gemini_err:
                    logger.debug("Gemini stream failed, falling back: %s", gemini_err)

            # --- Fallback: batch response chunked word-by-word ---
            async with _chat_semaphore:
                # Extract Permission Profile
                profile = PermissionProfile.SYSTEM_FULL
                if user is not None and user.role.value.lower() == "guest":
                    profile = PermissionProfile.READ_ONLY

                try:
                    response_text = await amadeus.handle_command(
                        user_input=message,
                        source=source,
                        permission_profile=profile,
                    )
                except QueueFullError as e:
                    raise HTTPException(status_code=429, detail=str(e))

            words = response_text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
                await asyncio.sleep(0.01)

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error("SSE stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': 'Stream error'})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )
