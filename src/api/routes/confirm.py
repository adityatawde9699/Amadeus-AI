"""
Confirmation API route for Amadeus AI Assistant.

Exposes ``POST /api/v1/confirm/{request_id}`` and
``GET  /api/v1/confirm/{request_id}`` so the frontend (Tauri desktop or
web client) can respond to HITL approval requests raised by the
``APIConfirmationCallback`` when a destructive tool tries to execute.

The ``APIConfirmationCallback`` singleton is stored on ``app.state`` and
injected here via FastAPI's dependency injection system.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class ConfirmRequest(BaseModel):
    """Body for the approval/denial POST request."""
    approved: bool


class ConfirmStatusResponse(BaseModel):
    """Status of a pending confirmation request."""
    request_id: str
    tool_name: str
    args: dict
    preview: str
    status: str  # "pending" | "approved" | "denied" | "not_found"


# =============================================================================
# DEPENDENCY: Get callback singleton from app.state
# =============================================================================

def get_confirmation_callback(request: Request):
    """Retrieve the shared APIConfirmationCallback from application state."""
    callback = getattr(request.app.state, "confirmation_callback", None)
    if callback is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Confirmation service not initialized.",
        )
    return callback


# =============================================================================
# ROUTES
# =============================================================================

@router.post(
    "/confirm/{request_id}",
    summary="Approve or deny a pending tool execution",
    status_code=status.HTTP_200_OK,
)
async def resolve_confirmation(
    request_id: str,
    body: ConfirmRequest,
    callback=Depends(get_confirmation_callback),
):
    """
    Resolve a HITL confirmation request.

    - ``approved: true``  → the tool will proceed with execution.
    - ``approved: false`` → the tool call will be aborted.

    Returns 404 if the ``request_id`` is unknown (already resolved or timed out).
    """
    resolved = callback.approve(request_id, body.approved)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Confirmation request '{request_id}' not found or already resolved.",
        )
    return {
        "status": "approved" if body.approved else "denied",
        "request_id": request_id,
    }


@router.get(
    "/confirm/{request_id}",
    response_model=ConfirmStatusResponse,
    summary="Check the status of a pending confirmation",
)
async def get_confirmation_status(
    request_id: str,
    callback=Depends(get_confirmation_callback),
):
    """
    Return the current status of a pending HITL confirmation request.

    Useful for polling-based clients that cannot use WebSockets.
    """
    pending = callback.get_pending(request_id)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Confirmation request '{request_id}' not found or already resolved.",
        )
    return ConfirmStatusResponse(
        request_id=pending.request_id,
        tool_name=pending.tool_name,
        args=pending.args,
        preview=pending.preview,
        status="pending",
    )



@router.get(
    "/confirm",
    summary="List all pending confirmation requests (admin/debug)",
)
async def list_pending_confirmations(
    callback=Depends(get_confirmation_callback),
):
    """List all currently pending HITL approval requests."""
    return {"pending": callback.list_pending()}
