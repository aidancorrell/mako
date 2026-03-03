"""Web fetch tool — fetches a URL and returns content."""

import logging
import re

import httpx

logger = logging.getLogger(__name__)

TOOL_NAME = "web_fetch"
TOOL_DESCRIPTION = "Fetch a web page and return its text content. Useful for reading articles, documentation, and web data."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch",
        },
    },
    "required": ["url"],
}

MAX_CONTENT_LENGTH = 8000  # Characters to return to the LLM


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
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mako/0.1 (AI Agent)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "html" in content_type:
        text = _strip_html(text)

    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + f"\n\n[Truncated — {len(resp.text)} chars total]"

    return text
