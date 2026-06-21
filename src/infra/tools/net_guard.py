"""
SSRF egress guard for outbound HTTP tools (Phase 3.1).

Centralizes the validation that an outbound URL points at a *public* internet
host, never at loopback / private / link-local / cloud-metadata addresses. This
defends ``fetch_webpage_content`` (and any future fetcher) against
Server-Side Request Forgery, where a model is tricked into reading internal
services (e.g. ``http://169.254.169.254/`` or ``http://localhost:6379``).

Design (fail closed):
  * Only ``http`` / ``https`` schemes are allowed.
  * The hostname is resolved to *all* of its A/AAAA records; if *any* resolved
    address is non-global, the request is denied (prevents DNS-rebinding and
    multi-record bypasses).
  * Redirects must be validated per-hop by the caller (see ``fetch_text``),
    because the final address — not just the first — must be public.
  * A development escape hatch (``ALLOW_PRIVATE_NETWORK_FETCH``) exists for
    local testing only; it is ``False`` by default and ignored in production.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


# Conservative caps shared by all fetchers.
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MiB hard ceiling on downloaded bytes
DEFAULT_TIMEOUT = 15.0
DEFAULT_DNS_TIMEOUT = 5.0  # cap on a single name-resolution (fail closed on stall)


class UrlNotAllowedError(ValueError):
    """Raised when a URL is rejected by the SSRF egress policy."""


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    """True only for globally-routable unicast addresses."""
    # ``is_global`` is the strictest single check, but be explicit for clarity
    # and to cover stdlib versions where mapped/reserved handling varies.
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) must be unwrapped and re-checked.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _ip_is_public(mapped)
    return bool(getattr(ip, "is_global", True))


def _resolve_addresses(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve *host* to every A/AAAA record. Raises on failure (fail closed)."""
    # A bare IP literal needs no DNS lookup.
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    addrs: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        addrs.append(ipaddress.ip_address(sockaddr[0]))
    if not addrs:
        raise UrlNotAllowedError(f"Could not resolve host: {host!r}")
    return addrs


def _validate_scheme_host(url: str) -> str:
    """Validate scheme + presence of host (no DNS). Returns the host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UrlNotAllowedError("URL must use http:// or https://")
    host = parts.hostname
    if not host:
        raise UrlNotAllowedError("URL has no host")
    return host


def _check_addresses(host: str, addresses: list[ipaddress._BaseAddress]) -> None:
    for ip in addresses:
        if not _ip_is_public(ip):
            raise UrlNotAllowedError(
                f"Refusing to fetch non-public address {ip} for host {host!r}"
            )


def assert_public_url(url: str, *, allow_private: bool = False) -> str:
    """
    Validate that *url* is safe to fetch (synchronous). Returns the URL.

    NOTE: this performs a blocking DNS lookup; prefer ``assert_public_url_async``
    on the event loop. Kept synchronous for non-async callers and tests.

    Raises ``UrlNotAllowedError`` when the scheme is unsupported, the host is
    missing/unresolvable, or any resolved address is non-public.
    """
    host = _validate_scheme_host(url)
    if allow_private:
        return url
    try:
        addresses = _resolve_addresses(host)
    except (socket.gaierror, OSError) as exc:
        raise UrlNotAllowedError(f"Host resolution failed for {host!r}") from exc
    _check_addresses(host, addresses)
    return url


async def assert_public_url_async(
    url: str, *, allow_private: bool = False, dns_timeout: float = DEFAULT_DNS_TIMEOUT
) -> str:
    """
    Async SSRF validation. Resolves DNS off the event loop (``asyncio.to_thread``)
    with a hard timeout so a slow/hostile resolver cannot stall the single-worker
    daemon. Returns the URL or raises ``UrlNotAllowedError`` (fail closed).
    """
    host = _validate_scheme_host(url)
    if allow_private:
        return url
    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(_resolve_addresses, host), dns_timeout
        )
    except TimeoutError as exc:
        raise UrlNotAllowedError(f"DNS resolution timed out for {host!r}") from exc
    except (socket.gaierror, OSError) as exc:
        raise UrlNotAllowedError(f"Host resolution failed for {host!r}") from exc
    _check_addresses(host, addresses)
    return url


async def fetch_text(
    url: str,
    *,
    allow_private: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = "AmadeusAI/2.0 WebResearchBot",
) -> httpx.Response:
    """
    Fetch *url* with SSRF protection, manual per-hop redirect validation, and a
    streamed size cap. Returns the final ``httpx.Response`` (already read).

    Every hop (including each redirect ``Location``) is re-validated with
    ``assert_public_url_async`` (DNS resolved off the event loop) so a public URL
    cannot bounce the client to an internal address.
    """
    current = await assert_public_url_async(url, allow_private=allow_private)
    headers = {"User-Agent": user_agent}

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, headers=headers
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        resp.raise_for_status()
                        raise UrlNotAllowedError("Redirect without Location header")
                    # Resolve relative redirects against the current URL, then
                    # re-validate the absolute destination.
                    current = await assert_public_url_async(
                        str(resp.url.join(location)), allow_private=allow_private
                    )
                    continue

                resp.raise_for_status()

                chunks: list[bytes] = []
                downloaded = 0
                async for chunk in resp.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise UrlNotAllowedError(
                            f"Response exceeded {max_bytes} byte cap"
                        )
                    chunks.append(chunk)

                # Populate .text/.content from the streamed body we just read.
                resp._content = b"".join(chunks)
                return resp

    raise UrlNotAllowedError(f"Too many redirects (>{MAX_REDIRECTS})")
