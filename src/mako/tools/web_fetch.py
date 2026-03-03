"""Web fetch tool — fetches a URL and returns content."""

import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

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

MAX_CONTENT_LENGTH = 8000  # Characters to return to the LLM
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB max download


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
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(
                f"URL resolves to private/reserved IP ({ip}). "
                "Requests to internal networks are blocked."
            )

    return url


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


async def web_fetch(url: str) -> str:
    """Fetch a URL and return its text content."""
    url = _validate_url(url)

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=False,
        headers={"User-Agent": "Mako/0.1"},
        max_redirects=0,
    ) as client:
        resp = await client.get(url)

        # Handle redirects manually with SSRF check on each hop
        redirects = 0
        while resp.is_redirect and redirects < 5:
            redirects += 1
            location = resp.headers.get("location", "")
            if not location:
                break
            location = urljoin(url, location)
            location = _validate_url(location)
            url = location
            resp = await client.get(location)

        resp.raise_for_status()

    # Check response size
    content_length = len(resp.content)
    if content_length > MAX_RESPONSE_BYTES:
        return f"Error: Response too large ({content_length} bytes, max {MAX_RESPONSE_BYTES})"

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "html" in content_type:
        text = _strip_html(text)

    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + f"\n\n[Truncated — {len(resp.text)} chars total]"

    return text
