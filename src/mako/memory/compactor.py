"""Context compaction — summarizes older messages when approaching token limits."""

import json
import logging

from mako.providers.base import Message, Provider

logger = logging.getLogger(__name__)

CONTEXT_LIMITS: dict[str, int] = {
    "claude": 200_000,
    "gemini": 1_000_000,
}

SUMMARIZE_PROMPT = (
    "You are a conversation summarizer. Condense the following conversation "
    "into a concise summary that preserves all key information: facts discussed, "
    "decisions made, tool results, user preferences, and any ongoing tasks. "
    "Write in third person. Be thorough but concise.\n\n"
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def count_message_tokens(messages: list[Message]) -> int:
    """Estimate total tokens across all messages."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.content)
        for tc in msg.tool_calls:
            total += estimate_tokens(tc.name)
            total += estimate_tokens(json.dumps(tc.arguments))
    return total


class ContextCompactor:
    """Compacts conversation history when it approaches the context limit."""

    def __init__(
        self,
        provider: Provider,
        context_limit_tokens: int = 200_000,
        compaction_trigger_ratio: float = 0.75,
        keep_recent_messages: int = 10,
    ) -> None:
        self.provider = provider
        self.context_limit = context_limit_tokens
        self.trigger_ratio = compaction_trigger_ratio
        self.keep_recent = keep_recent_messages
        self.threshold = int(self.context_limit * self.trigger_ratio)

    async def compact_if_needed(self, messages: list[Message]) -> list[Message]:
        """Compact messages if token count exceeds threshold.

        Returns messages unchanged if under threshold.
        """
        token_count = count_message_tokens(messages)

        if token_count < self.threshold:
            logger.debug("Context size OK: %d tokens (threshold %d)", token_count, self.threshold)
            return messages

        logger.info(
            "Context size %d tokens exceeds threshold %d — compacting",
            token_count, self.threshold,
        )
        try:
            return await self._compact(messages)
        except Exception:
            logger.exception("Compaction failed, returning original messages")
            return messages

    async def _compact(self, messages: list[Message]) -> list[Message]:
        """Split messages into system + middle + recent, summarize middle."""
        system_msgs: list[Message] = []
        rest: list[Message] = []

        for msg in messages:
            if msg.role == "system":
                system_msgs.append(msg)
            else:
                rest.append(msg)

        if len(rest) <= self.keep_recent:
            logger.debug("Not enough non-system messages to compact (%d)", len(rest))
            return messages

        to_summarize = rest[:-self.keep_recent]
        recent = rest[-self.keep_recent:]

        summary_text = await self._summarize_messages(to_summarize)
        summary_msg = Message(
            role="user",
            content=f"[Conversation Summary]\n{summary_text}\n[End Summary]",
        )

        logger.info(
            "Compacted %d messages into summary (%d tokens -> ~%d tokens)",
            len(to_summarize),
            count_message_tokens(to_summarize),
            estimate_tokens(summary_text),
        )

        return system_msgs + [summary_msg] + recent

    async def _summarize_messages(self, messages: list[Message]) -> str:
        """Format messages as text and ask the provider to summarize."""
        formatted = self._format_messages(messages)
        prompt_msg = Message(
            role="user",
            content=SUMMARIZE_PROMPT + formatted,
        )
        response = await self.provider.chat([prompt_msg])
        return response.content

    @staticmethod
    def _format_messages(messages: list[Message]) -> str:
        """Format messages into readable text for summarization."""
        lines: list[str] = []
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    lines.append(f"[Called tool: {tc.name}]")
                if msg.content:
                    lines.append(f"Assistant: {msg.content}")
            elif msg.role == "tool":
                preview = msg.content[:100]
                if len(msg.content) > 100:
                    preview += "..."
                lines.append(f"[Tool {msg.name} result: {preview}]")
            else:
                lines.append(f"{msg.role.title()}: {msg.content}")
        return "\n".join(lines)
