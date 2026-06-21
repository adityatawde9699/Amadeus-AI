"""
Per-IP pre-auth rate limiting (Phase 4.3).

A dependency-free, in-process fixed-window limiter applied to unauthenticated,
abuse-prone authentication endpoints (login / register / forgot-password /
verify) *before* credentials are validated. This blunts credential-stuffing and
account-enumeration bursts from a single source without adding a heavyweight
rate-limit dependency (keeping the daemon within its memory budget).

Notes / limitations:
  * State is per-process. With multiple workers each gets its own window; for a
    hard distributed limit a shared store (Redis) would be required. This is a
    deliberate, documented trade-off — it still meaningfully throttles a single
    attacker hammering one process and is the common deployment (1 worker).
  * The client IP is taken from ``X-Forwarded-For`` only when
    ``TRUST_PROXY_HEADERS`` is enabled (so it can't be spoofed when not behind a
    trusted proxy); otherwise the socket peer is used.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.core.config import get_settings


if TYPE_CHECKING:
    from starlette.requests import Request


# Path suffixes (under any /api/.../auth prefix) that are rate limited pre-auth.
_PROTECTED_SUFFIXES = (
    "/auth/jwt/login",
    "/auth/register",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/request-verify-token",
    "/auth/verify",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-IP limiter for sensitive auth endpoints."""

    # Backstop so a flood of distinct source IPs cannot grow the table without
    # bound (a memory-exhaustion amplifier on the <300MB daemon). When exceeded,
    # the table is swept immediately regardless of the time-based sweep.
    _MAX_TRACKED_IPS = 10_000

    def __init__(self, app) -> None:
        super().__init__(app)
        # ip -> deque[timestamp] of recent hits within the window.
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep: float = 0.0

    def _sweep(self, now: float, window: float) -> None:
        """Evict IP buckets with no hits inside the current window.

        Without this the dict keys (one per source IP ever seen) live forever
        even after their deques empty — an unbounded leak. Called opportunistically
        once per window, or immediately when the table exceeds the hard cap.
        """
        cutoff = now - window
        stale = [
            ip
            for ip, bucket in self._hits.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for ip in stale:
            del self._hits[ip]
        self._last_sweep = now

    def _client_ip(self, request: Request) -> str:
        settings = get_settings()
        if getattr(settings, "TRUST_PROXY_HEADERS", False):
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _is_protected(path: str) -> bool:
        return any(path.endswith(suffix) for suffix in _PROTECTED_SUFFIXES)

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not getattr(settings, "RATE_LIMIT_ENABLED", True) or not self._is_protected(
            request.url.path
        ):
            return await call_next(request)

        limit = settings.RATE_LIMIT_AUTH_REQUESTS
        window = settings.RATE_LIMIT_AUTH_WINDOW_SECONDS
        now = time.monotonic()
        ip = self._client_ip(request)

        # Opportunistic eviction: once per window, or immediately if the table
        # has grown past the hard cap. Bounds memory under a distributed flood.
        if (now - self._last_sweep) >= window or len(self._hits) > self._MAX_TRACKED_IPS:
            self._sweep(now, window)

        bucket = self._hits[ip]
        # Drop timestamps that have aged out of the window.
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = int(window - (now - bucket[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        bucket.append(now)
        return await call_next(request)
