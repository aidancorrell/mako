"""Abstract provider interface for LLM backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """A message in the conversation.

    role: "system", "user", "assistant", or "tool"
    """
    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""  # For tool result messages
    name: str = ""  # Tool name for tool result messages


class Provider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> Message:
        """Send messages to the LLM and get a response.

        Args:
            messages: Conversation history.
            tools: Tool definitions in JSON Schema format.

        Returns:
            The assistant's response message (may contain tool_calls).
        """
        ...
