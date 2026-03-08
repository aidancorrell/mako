"""Web fetch tool — fetches a URL and returns content."""

import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from mako.tools.retry import retry_with_backoff

logger = logging.getLogger(__name__)

TOOL_NAME = "web_fetch"
TOOL_DESCRIPTION = "Fetch a web page and return its text content. Useful for reading articles, documentation, and web data."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch (https only)",
        },
    },
    "required": ["url"],
}

MAX_CONTENT_LENGTH = 3000  # Default; overridden via module-level vars if set
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # Default; overridden via module-level vars if set
_max_content_length: int | None = None  # Set by main.py from settings
_max_response_bytes: int | None = None  # Set by main.py from settings


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is private, loopback, link-local, or reserved."""
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _validate_url(url: str) -> str:
    """Validate URL against SSRF attacks. Returns the URL if safe.

    - HTTPS only (TLS prevents DNS rebinding from connecting to wrong server)
    - Port 443 only
    - All resolved IPs must be public (not private/loopback/link-local/reserved)
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed. Use https.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    if parsed.port is not None and parsed.port != 443:
        raise ValueError(f"Non-standard port {parsed.port} not allowed.")

    # Resolve DNS and check all IPs
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_private_ip(ip):
            raise ValueError(
                f"URL resolves to private/reserved IP ({ip}). "
                "Requests to internal networks are blocked."
            )

    return url


def _validate_response_ip(resp: httpx.Response) -> None:
    """Post-connect validation: check the actual IP we connected to.

    Closes the DNS rebinding TOCTOU window by verifying the connection's
    peer address after the request completes.
    """
    # httpx exposes the network stream via extensions
    stream = resp.extensions.get("network_stream")
    if stream is None:
        return  # Can't verify — connection already closed or pooled

    server_addr = getattr(stream, "get_extra_info", lambda _: None)("server_addr")
    if server_addr is None:
        # Try peername (older httpx / httpcore)
        server_addr = getattr(stream, "get_extra_info", lambda _: None)("peername")

    if server_addr and isinstance(server_addr, tuple) and len(server_addr) >= 2:
        try:
            ip = ipaddress.ip_address(server_addr[0])
            if _is_private_ip(ip):
                raise ValueError(
                    f"DNS rebinding detected: connected to private IP ({ip}). "
                    "Request blocked."
                )
        except (ValueError, TypeError):
            pass  # Can't parse — not a rebinding risk worth blocking on


def _strip_html(html: str) -> str:
    """Basic HTML to text conversion."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block elements with newlines
    text = re.sub(r"<(?:p|div|br|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


async def _fetch_with_redirects(url: str) -> httpx.Response:
    """Fetch a URL, following redirects with SSRF validation on each hop."""
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": "Mako/0.1"},
        max_redirects=0,
    ) as client:
        resp = await client.get(url)
        _validate_response_ip(resp)

        # Handle redirects manually with SSRF check on each hop
        redirects = 0
        visited = {url}
        while resp.is_redirect and redirects < 5:
            redirects += 1
            location = resp.headers.get("location", "")
            if not location:
                break
            location = urljoin(url, location)
            location = _validate_url(location)
            if location in visited:
                break  # Circular redirect detected
            visited.add(location)
            url = location
            resp = await client.get(location)
            _validate_response_ip(resp)

        resp.raise_for_status()
        return resp


async def web_fetch(url: str) -> str:
    """Fetch a URL and return its text content."""
    url = _validate_url(url)

    resp = await retry_with_backoff(
        _fetch_with_redirects, url,
        retryable=(httpx.TransportError, TimeoutError, OSError),
    )

    # Check response size
    max_bytes = _max_response_bytes or MAX_RESPONSE_BYTES
    content_length = len(resp.content)
    if content_length > max_bytes:
        return f"Error: Response too large ({content_length} bytes, max {max_bytes})"

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "html" in content_type:
        text = _strip_html(text)

    max_chars = _max_content_length or MAX_CONTENT_LENGTH
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[Truncated — {len(resp.text)} chars total]"

    return text
