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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.api.middleware.rbac import RequireUser
from src.infra.persistence.orm_models import UserORM, UserRoleDB


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


def get_confirmation_callback(request: Request) -> Any:
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


def _not_found(request_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Confirmation request '{request_id}' not found or already resolved.",
    )


def _is_admin(user: UserORM) -> bool:
    return user.role == UserRoleDB.ADMIN


async def _owned_pending(callback: Any, request_id: str, user: UserORM) -> Any:
    """Return the pending request if ``user`` may act on it, else raise 404.

    REST chat sessions are keyed by ``str(user.id)``, so a confirmation raised
    during a user's chat is owned by that id. Admins may act on any request.
    A non-owner gets 404 (not 403) so request ids cannot be probed.
    """
    pending = await callback.aget_pending(request_id)
    if pending is None:
        raise _not_found(request_id)
    if not _is_admin(user) and not callback.is_owner(pending, str(user.id)):
        raise _not_found(request_id)
    return pending


@router.post(
    "/confirm/{request_id}",
    summary="Approve or deny a pending tool execution",
    status_code=status.HTTP_200_OK,
)
async def resolve_confirmation(
    request_id: str,
    body: ConfirmRequest,
    callback: Any = Depends(get_confirmation_callback),
    user: UserORM = Depends(RequireUser),
) -> dict[str, str]:
    """
    Resolve a HITL confirmation request owned by the caller.

    - ``approved: true``  → the tool will proceed with execution.
    - ``approved: false`` → the tool call will be aborted.

    Returns 404 if the ``request_id`` is unknown, already resolved, timed out,
    or owned by another user.
    """
    await _owned_pending(callback, request_id, user)
    if not await callback.aapprove(request_id, body.approved):
        raise _not_found(request_id)
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
    callback: Any = Depends(get_confirmation_callback),
    user: UserORM = Depends(RequireUser),
) -> ConfirmStatusResponse:
    """
    Return the current status of a pending HITL confirmation request owned by
    the caller. Useful for polling-based clients that cannot use WebSockets.
    """
    pending = await _owned_pending(callback, request_id, user)
    return ConfirmStatusResponse(
        request_id=pending.request_id,
        tool_name=pending.tool_name,
        args=pending.args,
        preview=pending.preview,
        status="pending",
    )


@router.get(
    "/confirm",
    summary="List pending confirmation requests (own requests; admins see all)",
)
async def list_pending_confirmations(
    callback: Any = Depends(get_confirmation_callback),
    user: UserORM = Depends(RequireUser),
) -> dict[str, list[Any]]:
    """List pending HITL approval requests visible to the caller."""
    session_filter = None if _is_admin(user) else str(user.id)
    return {"pending": await callback.alist_pending(session_filter)}
