"""Shell tool — execute allowlisted commands only.

The SecurityGuard validates the command against the allowlist before execution.
This module just runs it and captures output.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mako.security import SecurityGuard

logger = logging.getLogger(__name__)

# Set by main.py at startup so shell can reuse parsed args from SecurityGuard
_security: "SecurityGuard | None" = None

TOOL_NAME = "shell"
TOOL_DESCRIPTION = (
    "Execute a shell command. Only allowlisted commands are permitted "
    "(date by default). "
    "Use this for checking the current time. Use the web_fetch tool for URLs."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The shell command to execute",
        },
    },
    "required": ["command"],
}

MAX_OUTPUT_LENGTH = 8000  # Default; overridden via _max_output_length if set
_max_output_length: int | None = None  # Set by main.py from settings


async def shell(command: str) -> str:
    """Execute a command and return stdout/stderr.

    Security note: The SecurityGuard validates the command allowlist and
    rejects shell metacharacters BEFORE this function is ever called.
    We use create_subprocess_exec (not _shell) so the OS executes the
    command directly — no shell interpretation of pipes, redirects, etc.
    """
    # Reuse parsed args from SecurityGuard (already validated in pre_tool_call)
    if _security is not None:
        args = _security.validate_command(command)
    else:
        import shlex
        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"Error: failed to parse command: {e}"

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        return "Error: command timed out after 30 seconds"

    output = ""
    if stdout:
        output += stdout.decode(errors="replace")
    if stderr:
        output += f"\n[stderr]\n{stderr.decode(errors='replace')}"

    if not output.strip():
        output = f"(Command exited with code {proc.returncode}, no output)"

    max_len = _max_output_length or MAX_OUTPUT_LENGTH
    if len(output) > max_len:
        output = output[:max_len] + "\n\n[Truncated]"

    return output.strip()
