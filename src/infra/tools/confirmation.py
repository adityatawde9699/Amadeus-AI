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
  treated as a denial. In-process state: single worker only.
- ``RedisConfirmationCallback``   — same contract with pending requests and
  decisions in Redis, so any API worker can list/resolve a confirmation that
  another worker is waiting on (``SHARED_STATE_BACKEND=redis``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from redis.asyncio import Redis


logger = logging.getLogger(__name__)

# Session that owns the confirmation currently being requested. Set by
# ``ToolExecutor`` around ``request_approval()`` so callbacks can bind a pending
# request to its owner without changing the ``request_approval`` signature.
confirmation_owner: ContextVar[str | None] = ContextVar("confirmation_owner", default=None)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class PendingConfirmation:
    """State held while waiting for a user approval decision.

    Carries owner identity (user/session/source/profile) so a confirmation can
    only be inspected or resolved by the request that created it.
    """

    request_id: str
    tool_name: str
    args: dict[str, Any]
    preview: str = ""
    # Owner identity — used for ownership checks on resolution.
    user_id: str | None = None
    session_id: str | None = None
    source: str | None = None
    permission_profile: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    # Set by the in-process callback; None for records read back from Redis.
    future: asyncio.Future[bool] | None = None


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
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        confirmation = PendingConfirmation(
            request_id=request_id,
            tool_name=tool_name,
            args=args,
            preview=preview,
            session_id=confirmation_owner.get(),
            future=future,
        )
        self._pending[request_id] = confirmation

        logger.info(
            "confirmation_pending",
            extra={"tool": tool_name, "request_id": request_id},
        )

        try:
            # Block until approved/denied OR timeout
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
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

        if pending.future is not None and not pending.future.done():
            pending.future.set_result(approved)
            logger.info(
                "confirmation_resolved",
                extra={"request_id": request_id, "approved": approved},
            )
        return True

    def get_pending(self, request_id: str) -> PendingConfirmation | None:
        """Return the pending confirmation record, or None if not found."""
        return self._pending.get(request_id)

    @staticmethod
    def is_owner(pending: PendingConfirmation, session_id: str | None) -> bool:
        """True if ``session_id`` owns ``pending``. Unowned requests match nobody."""
        return pending.session_id is not None and pending.session_id == session_id

    def list_pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Return pending confirmations, optionally only those owned by ``session_id``."""
        return [
            {
                "request_id": p.request_id,
                "tool_name": p.tool_name,
                "args": p.args,
                "preview": p.preview,
                "created_at": p.created_at.isoformat(),
            }
            for p in self._pending.values()
            if session_id is None or self.is_owner(p, session_id)
        ]

    # Async accessors — what the API routes call, so the in-process and Redis
    # backends are interchangeable.
    async def aapprove(self, request_id: str, approved: bool) -> bool:
        return self.approve(request_id, approved)

    async def aget_pending(self, request_id: str) -> PendingConfirmation | None:
        return self.get_pending(request_id)

    async def alist_pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_pending(session_id)


# =============================================================================
# REDIS (MULTI-WORKER) IMPLEMENTATION
# =============================================================================


class RedisConfirmationCallback(APIConfirmationCallback):
    """HITL gate whose pending state lives in Redis.

    The worker running the tool stores the request under
    ``amadeus:hitl:pending:{id}`` (TTL = timeout) and blocks on ``BLPOP
    amadeus:hitl:decision:{id}``. Whichever worker receives
    ``POST /confirm/{id}`` pushes the decision; the waiter wakes up. Timeouts
    and an unknown/expired id still mean *deny* (fail closed). The ownership
    check (``is_owner``) is unchanged.
    """

    PREFIX = "amadeus:hitl"

    def __init__(self, redis: Redis, timeout_seconds: int = 60) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._redis = redis

    def _pending_key(self, request_id: str) -> str:
        return f"{self.PREFIX}:pending:{request_id}"

    def _decision_key(self, request_id: str) -> str:
        return f"{self.PREFIX}:decision:{request_id}"

    @property
    def _index_key(self) -> str:
        return f"{self.PREFIX}:index"

    @property
    def _ttl(self) -> int:
        return max(1, int(self.timeout_seconds) + 5)

    async def request_approval(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_id: str,
        preview: str = "",
    ) -> bool:
        record = {
            "request_id": request_id,
            "tool_name": tool_name,
            "args": args,
            "preview": preview,
            "session_id": confirmation_owner.get(),
            "created_at": datetime.now().isoformat(),
        }
        pending_key, decision_key = self._pending_key(request_id), self._decision_key(request_id)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.set(pending_key, json.dumps(record, default=str), ex=self._ttl)
                pipe.zadd(self._index_key, {request_id: time.time()})
                await pipe.execute()
            logger.info("confirmation_pending", extra={"tool": tool_name, "request_id": request_id})
            popped: Any = await self._redis.blpop(  # type: ignore[misc]
                [decision_key], timeout=self.timeout_seconds
            )
        except Exception:
            logger.exception("confirmation_redis_error", extra={"request_id": request_id})
            return False  # fail closed
        finally:
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.delete(pending_key, decision_key)
                    pipe.zrem(self._index_key, request_id)
                    await pipe.execute()
            except Exception:
                logger.warning(
                    "confirmation_redis_cleanup_failed", extra={"request_id": request_id}
                )
        if popped is None:
            logger.warning(
                "confirmation_timeout", extra={"tool": tool_name, "request_id": request_id}
            )
            return False
        return _as_str(popped[1]) == "1"

    async def aapprove(self, request_id: str, approved: bool) -> bool:
        if not await self._redis.exists(self._pending_key(request_id)):
            logger.warning("confirmation_unknown_request_id", extra={"request_id": request_id})
            return False
        decision_key = self._decision_key(request_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(decision_key, "1" if approved else "0")
            pipe.expire(decision_key, self._ttl)
            await pipe.execute()
        logger.info("confirmation_resolved", extra={"request_id": request_id, "approved": approved})
        return True

    async def aget_pending(self, request_id: str) -> PendingConfirmation | None:
        raw = await self._redis.get(self._pending_key(request_id))
        return self._decode(raw)

    async def alist_pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        ids = [_as_str(i) for i in await self._redis.zrange(self._index_key, 0, -1)]
        if not ids:
            return []
        raws = await self._redis.mget([self._pending_key(i) for i in ids])
        expired = [i for i, raw in zip(ids, raws, strict=True) if raw is None]
        if expired:  # waiter died before cleanup; keep the index tidy
            await self._redis.zrem(self._index_key, *expired)
        out = []
        for raw in raws:
            pending = self._decode(raw)
            if pending and (session_id is None or self.is_owner(pending, session_id)):
                out.append(
                    {
                        "request_id": pending.request_id,
                        "tool_name": pending.tool_name,
                        "args": pending.args,
                        "preview": pending.preview,
                        "created_at": pending.created_at.isoformat(),
                    }
                )
        return out

    # Sync accessors can't reach Redis; fail loudly instead of returning stale data.
    def approve(self, request_id: str, approved: bool) -> bool:
        raise NotImplementedError("use 'await aapprove(...)' with the Redis backend")

    def get_pending(self, request_id: str) -> PendingConfirmation | None:
        raise NotImplementedError("use 'await aget_pending(...)' with the Redis backend")

    def list_pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("use 'await alist_pending(...)' with the Redis backend")

    @staticmethod
    def _decode(raw: Any) -> PendingConfirmation | None:
        if raw is None:
            return None
        data = json.loads(_as_str(raw))
        return PendingConfirmation(
            request_id=data["request_id"],
            tool_name=data["tool_name"],
            args=data.get("args") or {},
            preview=data.get("preview", ""),
            session_id=data.get("session_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


def _as_str(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


# =============================================================================
# FACTORY HELPER
# =============================================================================


def make_request_id() -> str:
    """Generate a new unique confirmation request ID."""
    return str(uuid.uuid4())


async def create_api_confirmation_callback(
    backend: str, redis_url: str | None, timeout_seconds: int = 60
) -> APIConfirmationCallback:
    """Build the REST HITL callback for ``SHARED_STATE_BACKEND``.

    ``"redis"`` pings Redis first and raises if it is unreachable: silently
    falling back to in-process state would make approvals sent to another
    worker vanish (every risky tool would time out and be denied).
    """
    if backend != "redis":
        return APIConfirmationCallback(timeout_seconds=timeout_seconds)
    if not redis_url:
        raise RuntimeError("SHARED_STATE_BACKEND=redis requires REDIS_URL")
    from redis.asyncio import from_url

    client = from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        raise RuntimeError(f"SHARED_STATE_BACKEND=redis but Redis is unreachable: {exc}") from exc
    return RedisConfirmationCallback(client, timeout_seconds=timeout_seconds)
