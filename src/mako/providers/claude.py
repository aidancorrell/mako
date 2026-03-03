"""Claude provider — calls Anthropic API via the official SDK.

Supports Anthropic's server-side web tools (web_search, web_fetch) which run
on Anthropic's infrastructure and return results within the same API response.
These are separate from Mako's local tools and bypass SecurityGuard entirely
since no local execution occurs.
"""

import logging

import anthropic

from .base import Message, Provider, ToolCall

logger = logging.getLogger(__name__)

MAX_PAUSE_CONTINUATIONS = 5


class ClaudeProvider(Provider):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        web_search: bool = False,
        web_fetch: bool = False,
    ) -> None:
        self.model = model
        self.web_search = web_search
        self.web_fetch = web_fetch
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return "claude"

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> Message:
        # Separate system message from conversation
        system_text = ""
        conversation: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_text += msg.content + "\n"
                continue

            if msg.role == "tool":
                conversation.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
                continue

            # Assistant message with raw content (preserves server-side tool blocks)
            if msg.role == "assistant" and msg.raw_content:
                conversation.append({"role": "assistant", "content": msg.raw_content})
                continue

            if msg.role == "assistant" and msg.tool_calls:
                content: list[dict] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                conversation.append({"role": "assistant", "content": content})
                continue

            conversation.append({"role": msg.role, "content": msg.content})

        # Build tools list: custom tools + server-side tools
        api_tools: list[dict] = []
        if tools:
            api_tools.extend(self._convert_tools(tools))
        if self.web_search:
            api_tools.append({
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            })
        if self.web_fetch:
            api_tools.append({
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 5,
            })

        # Build API call kwargs
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": conversation,
        }
        if system_text.strip():
            kwargs["system"] = system_text.strip()
        if api_tools:
            kwargs["tools"] = api_tools

        logger.debug("Claude request: %d messages, %d tools", len(conversation), len(api_tools))

        response = await self._client.messages.create(**kwargs)

        # Handle pause_turn: the API paused a long-running turn, continue it
        continuations = 0
        while response.stop_reason == "pause_turn" and continuations < MAX_PAUSE_CONTINUATIONS:
            continuations += 1
            logger.debug("Claude pause_turn, continuing (%d/%d)", continuations, MAX_PAUSE_CONTINUATIONS)
            conversation.append({
                "role": "assistant",
                "content": _serialize_content(response.content),
            })
            kwargs["messages"] = conversation
            response = await self._client.messages.create(**kwargs)

        return self._parse_response(response)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert our tool format to Anthropic's format."""
        result = []
        for tool in tools:
            func = tool.get("function", tool)
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _parse_response(self, response: anthropic.types.Message) -> Message:
        """Parse Anthropic response into our Message format.

        Handles standard text/tool_use blocks as well as server-side tool blocks
        (server_tool_use, web_search_tool_result, web_fetch_tool_result) which are
        executed by the API and don't need local processing.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        citations: list[dict] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                # Collect citations from text blocks (web search adds these)
                block_citations = getattr(block, "citations", None)
                if block_citations:
                    for cite in block_citations:
                        url = getattr(cite, "url", "")
                        title = getattr(cite, "title", "")
                        if url:
                            citations.append({"url": url, "title": title})
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))
            # server_tool_use, web_search_tool_result, web_fetch_tool_result
            # are handled server-side — no local processing needed

        content = "\n".join(text_parts)

        # Append citation sources to the response text
        if citations:
            seen: set[str] = set()
            sources: list[str] = []
            for cite in citations:
                if cite["url"] not in seen:
                    seen.add(cite["url"])
                    label = cite["title"] or cite["url"]
                    sources.append(f"- {label}: {cite['url']}")
            if sources:
                content += "\n\nSources:\n" + "\n".join(sources)

        # Preserve raw content blocks when server-side tools were used,
        # so multi-turn conversations can pass them back to the API
        has_server_blocks = any(
            block.type in ("server_tool_use", "web_search_tool_result", "web_fetch_tool_result")
            for block in response.content
        )
        raw_content = _serialize_content(response.content) if has_server_blocks else None

        return Message(
            role="assistant",
            content=content or "",
            tool_calls=tool_calls,
            raw_content=raw_content,
            stop_reason=response.stop_reason or "",
        )

    async def close(self) -> None:
        await self._client.close()


def _serialize_content(content: list) -> list[dict]:
    """Serialize response content blocks to dicts for API pass-through."""
    blocks = []
    for block in content:
        if hasattr(block, "model_dump"):
            blocks.append(block.model_dump())
        elif isinstance(block, dict):
            blocks.append(block)
    return blocks
