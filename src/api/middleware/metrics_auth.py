"""
Access control for the Prometheus ``/api/v1/metrics`` endpoint.

Prometheus scrapers can't log in through fastapi-users, so metrics use their own
gate: a static bearer token (``METRICS_TOKEN``) when configured, otherwise
loopback-only access so a same-host scraper keeps working while remote callers
cannot read request rates, routes, latencies and LLM usage.
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import HTTPException, Request, status

from src.core.config import get_settings


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def require_metrics_access(request: Request) -> None:
    """FastAPI dependency: allow the scrape or raise 401/403."""
    token = get_settings().METRICS_TOKEN
    if token:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid metrics token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return
    # The socket peer is used deliberately (not X-Forwarded-For): a proxied
    # request then appears to come from the proxy, so set METRICS_TOKEN when
    # running behind one.
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics are only available from localhost unless METRICS_TOKEN is set",
        )
