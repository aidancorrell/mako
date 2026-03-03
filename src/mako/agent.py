"""ReAct agent loop — the core of Mako.

Assembles context, sends to provider, handles tool calls, loops until done.
"""

import logging

from mako.config import Settings
from mako.context import ContextAssembler
from mako.memory.compactor import ContextCompactor
from mako.providers.base import Message, Provider
from mako.security import SecurityGuard
from mako.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """The ReAct agent loop.

    1. Assemble context (system prompt + personality + memory + history + tool definitions)
    2. Send to provider
    3. If tool call → SecurityGuard validates → execute → feed result back → loop
    4. If text response → return it
    5. Loop detection enforced by SecurityGuard
    """

    def __init__(
        self,
        provider: Provider,
        registry: ToolRegistry,
        security: SecurityGuard,
        settings: Settings,
        context: ContextAssembler,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.security = security
        self.settings = settings
        self.context = context
        self.compactor = ContextCompactor(
            provider=provider,
            context_limit_tokens=settings.context_limit_tokens,
            compaction_trigger_ratio=settings.compaction_trigger_ratio,
            keep_recent_messages=settings.keep_recent_messages,
        )

    async def run(
        self,
        user_message: str,
        history: list[Message] | None = None,
        session_id: str = "_default",
    ) -> str:
        """Run the agent loop for a single user turn.

        Args:
            user_message: The user's input.
            history: Previous conversation messages (optional).
            session_id: Unique session identifier for rate-limit scoping.

        Returns:
            The agent's final text response.
        """
        self.security.reset_turn(session_id)

        messages = self.context.build_messages(user_message, history)
        tool_schemas = self.registry.get_tool_schemas()

        for iteration in range(self.settings.max_iterations):
            self.security.check_iteration_limit(iteration)

            if iteration == 0:
                messages = await self.compactor.compact_if_needed(messages)

            logger.debug("Agent iteration %d", iteration)
            response = await self.provider.chat(messages, tools=tool_schemas or None)

            if not response.tool_calls:
                # No tool calls — we have the final response
                return response.content or "(No response)"

            # Process tool calls
            messages.append(response)

            for tool_call in response.tool_calls:
                logger.info("Tool call: %s(%s)", tool_call.name,
                    ", ".join(tool_call.arguments.keys()))
                logger.debug("Tool args: %s(%s)", tool_call.name,
                    ", ".join(f"{k}={v!r}" for k, v in tool_call.arguments.items()),
                )

                result = await self.registry.execute(
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    reasoning=response.content,
                )

                messages.append(Message(
                    role="tool",
                    content=result,
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                ))

        # Hit max iterations
        return (
            "I've reached the maximum number of iterations for this turn. "
            "Here's what I have so far based on the tool results above."
        )
