"""Security module — gates every tool call. Built first, not bolted on."""

import json
import logging
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a tool call is denied by the security guard."""


class SecurityGuard:
    """Validates every tool call before execution.

    - Command allowlist for shell execution
    - Path jailing for workspace file access
    - Rate limiting (per-turn and per-minute)
    - Loop detection (max iterations per agent turn)
    - Audit logging of every tool invocation
    """

    def __init__(
        self,
        workspace_path: Path,
        safe_bins: list[str],
        max_tool_calls_per_turn: int = 20,
        max_tool_calls_per_minute: int = 30,
        max_iterations: int = 10,
    ) -> None:
        self.workspace_path = workspace_path.resolve()
        self.safe_bins = set(safe_bins)
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.max_tool_calls_per_minute = max_tool_calls_per_minute
        self.max_iterations = max_iterations

        # Rate limiting state
        self._turn_call_count = 0
        self._minute_calls: deque[float] = deque()

        # Audit log path
        self.audit_log_path = workspace_path / "audit.log"
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    def reset_turn(self) -> None:
        """Reset per-turn counters. Call at the start of each agent turn."""
        self._turn_call_count = 0

    def check_iteration_limit(self, iteration: int) -> None:
        """Enforce max iterations per agent turn."""
        if iteration >= self.max_iterations:
            raise SecurityError(
                f"Loop detection: reached max {self.max_iterations} iterations. "
                "Stopping to prevent runaway execution."
            )

    # Shell metacharacters that enable chaining, piping, or subshell execution
    SHELL_METACHARACTERS = set("|;&`$(){}!")

    def validate_command(self, command: str) -> list[str]:
        """Validate a shell command against the allowlist.

        Rejects shell metacharacters (pipes, chains, subshells, redirects)
        and returns the parsed argument list for safe execution via exec
        (not via shell).
        """
        import shlex

        cmd = command.strip()
        if not cmd:
            raise SecurityError("Empty command")

        # Reject any shell metacharacters before even parsing.
        # This blocks: pipes (|), chains (&&, ;), subshells ($(), ``),
        # redirects (> is caught by shlex as a token, but we block & and ; here)
        for char in self.SHELL_METACHARACTERS:
            if char in cmd:
                raise SecurityError(
                    f"Shell metacharacter '{char}' not allowed. "
                    "Commands cannot use pipes, chains, redirects, or subshells."
                )

        # Also block output redirects
        if ">" in cmd or "<" in cmd:
            raise SecurityError(
                "Redirects (> <) not allowed in shell commands."
            )

        # Parse into tokens safely
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            raise SecurityError(f"Failed to parse command: {e}")

        if not args:
            raise SecurityError("Empty command after parsing")

        base_cmd = Path(args[0]).name  # Handle /usr/bin/curl -> curl
        if base_cmd not in self.safe_bins:
            raise SecurityError(
                f"Command '{base_cmd}' not in allowlist. "
                f"Allowed: {sorted(self.safe_bins)}"
            )

        return args

    def validate_path(self, file_path: str) -> Path:
        """Resolve a path and ensure it's within the workspace.

        Returns the resolved absolute path if valid.
        Rejects symlinks that escape, ../ traversals, and absolute paths outside workspace.
        """
        # Resolve relative to workspace
        target = (self.workspace_path / file_path).resolve()

        # Check it's within workspace (resolve() follows symlinks)
        try:
            target.relative_to(self.workspace_path)
        except ValueError:
            raise SecurityError(
                f"Path '{file_path}' resolves to '{target}' which is outside "
                f"workspace '{self.workspace_path}'"
            )

        return target

    def check_rate_limit(self) -> None:
        """Enforce rate limits (per-turn and per-minute)."""
        # Per-turn limit
        self._turn_call_count += 1
        if self._turn_call_count > self.max_tool_calls_per_turn:
            raise SecurityError(
                f"Rate limit: exceeded {self.max_tool_calls_per_turn} tool calls this turn"
            )

        # Per-minute limit
        now = time.monotonic()
        self._minute_calls.append(now)
        # Evict calls older than 60 seconds
        while self._minute_calls and (now - self._minute_calls[0]) > 60:
            self._minute_calls.popleft()
        if len(self._minute_calls) > self.max_tool_calls_per_minute:
            raise SecurityError(
                f"Rate limit: exceeded {self.max_tool_calls_per_minute} tool calls per minute"
            )

    def audit(
        self,
        tool_name: str,
        args: dict,
        result: str | None = None,
        error: str | None = None,
        reasoning: str | None = None,
    ) -> None:
        """Log a tool invocation to the audit log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tool": tool_name,
            "args": args,
        }
        if result is not None:
            # Truncate long results in the audit log
            entry["result"] = result[:500] if len(result) > 500 else result
        if error is not None:
            entry["error"] = error
        if reasoning is not None:
            entry["reasoning"] = reasoning[:200] if len(reasoning) > 200 else reasoning

        line = json.dumps(entry, ensure_ascii=False)
        try:
            with open(self.audit_log_path, "a") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.error("Failed to write audit log: %s", e)

    def pre_tool_call(self, tool_name: str, args: dict) -> None:
        """Run all pre-execution checks. Call this before every tool execution."""
        self.check_rate_limit()

        # Tool-specific validation
        if tool_name == "shell":
            self.validate_command(args.get("command", ""))
        elif tool_name in ("read_file", "write_file"):
            self.validate_path(args.get("path", ""))
