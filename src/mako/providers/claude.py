"""Claude provider — calls Anthropic API via the official SDK."""

import logging

import anthropic

from .base import Message, Provider, ToolCall

logger = logging.getLogger(__name__)


class ClaudeProvider(Provider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

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

        # Build API call kwargs
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": conversation,
        }
        if system_text.strip():
            kwargs["system"] = system_text.strip()
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        logger.debug("Claude request: %d messages, %d tools", len(conversation), len(tools or []))

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
        """Parse Anthropic response into our Message format."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        return Message(
            role="assistant",
            content="\n".join(text_parts),
            tool_calls=tool_calls,
        )

    async def close(self) -> None:
        await self._client.close()
