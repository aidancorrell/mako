"""Tool registry — registers tools and generates JSON Schema definitions."""

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from mako.security import SecurityGuard

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    """A registered tool with its metadata and handler."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]


class ToolRegistry:
    """Manages tool registration and execution.

    Every tool call passes through SecurityGuard before the handler runs.
    """

    def __init__(self, security: SecurityGuard) -> None:
        self.security = security
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Awaitable[str]],
    ) -> None:
        """Register a tool."""
        self._tools[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )
        logger.debug("Registered tool: %s", name)

    def get_tool_schemas(self) -> list[dict]:
        """Generate JSON Schema tool definitions for the LLM."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return schemas

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        reasoning: str | None = None,
    ) -> str:
        """Execute a tool call with security checks and audit logging.

        Args:
            name: Tool name.
            arguments: Tool arguments from the LLM.
            reasoning: The LLM's reasoning for making this call (for audit).

        Returns:
            Tool result as a string.
        """
        if name not in self._tools:
            error = f"Unknown tool: {name}"
            self.security.audit(name, arguments, error=error)
            return f"Error: {error}"

        # Pre-execution security checks
        try:
            self.security.pre_tool_call(name, arguments)
        except Exception as e:
            error_msg = str(e)
            self.security.audit(name, arguments, error=error_msg, reasoning=reasoning)
            logger.warning("Security blocked tool call %s: %s", name, error_msg)
            return f"Error: {error_msg}"

        # Execute the tool
        try:
            result = await self._tools[name].handler(**arguments)
            self.security.audit(name, arguments, result=result, reasoning=reasoning)
            return result
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            self.security.audit(name, arguments, error=error_msg, reasoning=reasoning)
            logger.error("Tool %s failed: %s", name, error_msg)
            return f"Error: {error_msg}"

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
