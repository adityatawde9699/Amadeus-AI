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
    address is non-global, the request is denied (defeats multi-record bypasses).
  * DNS-rebinding is defeated by *pinning*: ``_PinnedPublicIPTransport`` resolves
    the host, validates every address, and connects the socket to a validated IP
    literal — so the HTTP client never performs a second, unvalidated DNS lookup
    between the check and the connection. The original hostname is preserved for
    the Host header and, via the ``sni_hostname`` extension, for TLS SNI and
    certificate verification.
  * Redirects are validated *and* re-pinned per hop (see ``fetch_text``), because
    the final address — not just the first — must be public.
  * A development escape hatch (``ALLOW_PRIVATE_NETWORK_FETCH``) exists for
    local testing only; it is ``False`` by default and ignored in production.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
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


async def _resolve_pinned_ip(host: str, *, dns_timeout: float = DEFAULT_DNS_TIMEOUT) -> str:
    """Resolve *host*, verify every address is public, and return one pinned IP.

    Resolving here — and then connecting to the returned literal — is what
    actually closes the DNS-rebinding window: the socket target is an IP we just
    validated, not a hostname the HTTP client would re-resolve at connect time.
    """
    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(_resolve_addresses, host), dns_timeout
        )
    except TimeoutError as exc:
        raise UrlNotAllowedError(f"DNS resolution timed out for {host!r}") from exc
    except (socket.gaierror, OSError) as exc:
        raise UrlNotAllowedError(f"Host resolution failed for {host!r}") from exc
    _check_addresses(host, addresses)
    return str(addresses[0])


class _PinnedPublicIPTransport(httpx.AsyncHTTPTransport):
    """SSRF-safe transport that pins each request to a pre-validated public IP.

    Overriding the transport (rather than only pre-checking the URL) is what
    defeats DNS rebinding: for every request *and* redirect hop httpx sends, we
    resolve + validate the host and rewrite the socket target to a validated IP
    literal, so httpcore never issues a second, unvalidated DNS lookup. The real
    hostname is preserved for the Host header (already set by httpx) and, via the
    ``sni_hostname`` extension, for TLS SNI and certificate verification.
    """

    def __init__(self, *, dns_timeout: float = DEFAULT_DNS_TIMEOUT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dns_timeout = dns_timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise UrlNotAllowedError("URL has no host")
        pinned = await _resolve_pinned_ip(host, dns_timeout=self._dns_timeout)
        # Keep the real hostname for TLS SNI + cert verification; only the socket
        # target changes. The Host header was already derived from the original URL.
        request.extensions["sni_hostname"] = host
        request.url = request.url.copy_with(host=pinned)
        return await super().handle_async_request(request)


async def fetch_text(
    url: str,
    *,
    allow_private: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_RESPONSE_BYTES,
    user_agent: str = "AmadeusAI/2.0 WebResearchBot",
) -> httpx.Response:
    """
    Fetch *url* with SSRF protection, per-hop redirect validation, IP pinning,
    and a streamed size cap. Returns the final ``httpx.Response`` (already read).

    Protection is enforced at two layers: ``assert_public_url_async`` gives a
    fast, clear rejection (scheme + public-host) for each hop, and
    ``_PinnedPublicIPTransport`` re-validates and pins every connection to a
    checked IP literal so a hostile resolver cannot rebind the hostname to an
    internal address between the check and the socket connect.
    """
    current = await assert_public_url_async(url, allow_private=allow_private)
    headers = {"User-Agent": user_agent}

    # In dev-only allow_private mode we skip pinning and use the default resolver.
    transport = None if allow_private else _PinnedPublicIPTransport()

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, headers=headers, transport=transport
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        resp.raise_for_status()
                        raise UrlNotAllowedError("Redirect without Location header")
                    # Resolve relative redirects against the *original-host* URL
                    # we requested (``current``), NOT ``resp.url`` — the pinning
                    # transport rewrites the request URL host to an IP literal, so
                    # ``resp.url`` no longer carries the hostname. Then re-validate
                    # the absolute destination (the transport re-pins on connect).
                    current = await assert_public_url_async(
                        str(httpx.URL(current).join(location)), allow_private=allow_private
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
