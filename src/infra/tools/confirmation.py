"""
Confirmation Callback System for Amadeus AI Tool Execution.

Provides a HUMAN-IN-THE-LOOP (HITL) gate for destructive tool operations.
Tools decorated with ``requires_confirmation=True`` will not execute until
the user explicitly approves via one of the callback implementations.

Implementations
---------------
- ``TerminalConfirmationCallback`` — CLI/test mode; blocks stdin until y/n.
- ``APIConfirmationCallback``     — HTTP server mode; blocks until the
  ``POST /api/v1/confirm/{request_id}`` endpoint is called or the timeout
  elapses.  A caller that does not respond within the timeout window is
  treated as a denial.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PendingConfirmation:
    """State held while waiting for a user approval decision."""

    request_id: str
    tool_name: str
    args: dict[str, Any]
    preview: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    future: asyncio.Future[bool] = field(default_factory=lambda: asyncio.get_event_loop().create_future())



# =============================================================================
# ABSTRACT BASE
# =============================================================================

class ConfirmationCallback(ABC):
    """
    Abstract gate that must be satisfied before a destructive tool executes.

    Subclasses decide HOW to ask for approval (stdin, HTTP, WebSocket, etc.)
    and return ``True`` (approved) or ``False`` (denied / timed-out).
    """

    @abstractmethod
    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_id: str,
        preview: str = "",
    ) -> bool:

        """
        Ask for user approval.

        Parameters
        ----------
        tool_name:  Name of the tool about to execute.
        args:       Arguments the LLM wants to pass to the tool.
        request_id: Stable UUID for this approval request (used by HTTP impl).

        Returns
        -------
        ``True``  → user approved; proceed with execution.
        ``False`` → user denied or timeout; abort execution.
        """


# =============================================================================
# TERMINAL (CLI / TEST) IMPLEMENTATION
# =============================================================================

class TerminalConfirmationCallback(ConfirmationCallback):
    """
    Interactive confirmation via stdin.

    Suitable for CLI usage, development, and unit/integration tests
    (where the test can pipe "y\\n" to stdin or monkeypatch this class).
    """

    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_id: str,
        preview: str = "",
    ) -> bool:
        print(
            f"\n⚠️  CONFIRMATION REQUIRED\n"
            f"   Tool:      {tool_name}\n"
            f"   Preview:   {preview}\n"
            f"   Arguments: {args}\n"
            f"   Request ID: {request_id}\n"
        )
        loop = asyncio.get_running_loop()
        # Run blocking stdin read in a thread so we don't block the event loop
        raw = await loop.run_in_executor(None, input, "   Approve? [y/N]: ")
        approved = raw.strip().lower() in ("y", "yes")
        logger.info(
            "terminal_confirmation",
            extra={"tool": tool_name, "request_id": request_id, "approved": approved},
        )
        return approved



# =============================================================================
# API / HTTP IMPLEMENTATION
# =============================================================================

class APIConfirmationCallback(ConfirmationCallback):
    """
    Confirmation gate for the FastAPI server.

    Flow
    ----
    1. ``request_approval()`` is called during tool execution.
    2. A ``PendingConfirmation`` record is stored in ``_pending``.
    3. The caller (API route) returns a 202 Accepted with the ``request_id``
       embedded in the response so the frontend can render an approval UI.
    4. When the user clicks Approve/Deny in the UI, the frontend calls
       ``POST /api/v1/confirm/{request_id}``.
    5. ``approve(request_id, decision)`` resolves the internal Future.
    6. ``request_approval()`` unblocks and returns the decision.
    7. If the timeout elapses without a decision, the Future is resolved False.

    Notes
    -----
    - Pending state is **in-memory only**; a server restart clears it.
      This is acceptable for Phase 1; Redis persistence comes in Phase 2.
    - The ``APIConfirmationCallback`` instance must be a **singleton** shared
      between the route handler and the ToolExecutor so they reference the same
      ``_pending`` dict.
    """

    def __init__(self, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = timeout_seconds
        self._pending: dict[str, PendingConfirmation] = {}

    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_id: str,
        preview: str = "",
    ) -> bool:
        loop = asyncio.get_running_loop()
        confirmation = PendingConfirmation(
            request_id=request_id,
            tool_name=tool_name,
            args=args,
            preview=preview,
            future=loop.create_future(),
        )
        self._pending[request_id] = confirmation


        logger.info(
            "confirmation_pending",
            extra={"tool": tool_name, "request_id": request_id},
        )

        try:
            # Block until approved/denied OR timeout
            return await asyncio.wait_for(
                asyncio.shield(confirmation.future),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "confirmation_timeout",
                extra={"tool": tool_name, "request_id": request_id},
            )
            return False
        finally:
            self._pending.pop(request_id, None)

    def approve(self, request_id: str, approved: bool) -> bool:
        """
        Resolve a pending confirmation from outside (called by the API route).

        Returns
        -------
        ``True``  if the request_id was found and resolved.
        ``False`` if the request_id is unknown (already timed out / not found).
        """
        pending = self._pending.get(request_id)
        if not pending:
            logger.warning(
                "confirmation_unknown_request_id",
                extra={"request_id": request_id},
            )
            return False

        if not pending.future.done():
            pending.future.set_result(approved)
            logger.info(
                "confirmation_resolved",
                extra={"request_id": request_id, "approved": approved},
            )
        return True

    def get_pending(self, request_id: str) -> PendingConfirmation | None:
        """Return the pending confirmation record, or None if not found."""
        return self._pending.get(request_id)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return a list of all pending confirmations (for admin/debug views)."""
        return [
            {
                "request_id": p.request_id,
                "tool_name": p.tool_name,
                "args": p.args,
                "preview": p.preview,
                "created_at": p.created_at.isoformat(),
            }
            for p in self._pending.values()
        ]



# =============================================================================
# FACTORY HELPER
# =============================================================================

def make_request_id() -> str:
    """Generate a new unique confirmation request ID."""
    return str(uuid.uuid4())
