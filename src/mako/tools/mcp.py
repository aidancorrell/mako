"""MCP client — connects to MCP servers via JSON-RPC over stdio.

Spawns an MCP server as a subprocess, discovers its tools, and registers
them into Mako's tool registry so the agent can use them natively.
"""

import asyncio
import json
import logging
from typing import Any

from mako.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for a single MCP server process.

    Communicates via JSON-RPC 2.0 over stdin/stdout.
    """

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None) -> None:
        self.name = name
        self.command = command
        self.env = env
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    @staticmethod
    def _build_safe_env(extra_env: dict[str, str] | None) -> dict[str, str]:
        """Build a sanitized environment for MCP subprocesses.

        Inherits basic system vars but strips API keys and secrets.
        """
        import os
        # Start with essential system vars only
        safe_keys = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"}
        env = {k: v for k, v in os.environ.items() if k in safe_keys}
        # Merge in any explicitly configured vars from mcp_servers.json
        if extra_env:
            env.update(extra_env)
        return env

    async def start(self) -> None:
        """Spawn the MCP server subprocess."""
        logger.info("Starting MCP server '%s': %s", self.name, " ".join(self.command))
        safe_env = self._build_safe_env(self.env)
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=safe_env,
        )
        self._reader_task = asyncio.create_task(self._read_responses())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Initialize the MCP connection
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mako", "version": "0.1.0"},
        })

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def stop(self) -> None:
        """Stop the MCP server subprocess."""
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._reader_task:
            self._reader_task.cancel()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        logger.info("Stopped MCP server '%s'", self.name)

    async def list_tools(self) -> list[dict]:
        """Discover available tools from the MCP server."""
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server and return the result as text."""
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        # MCP tool results are an array of content blocks
        content = result.get("content", [])
        text_parts = []
        for block in content:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            else:
                text_parts.append(json.dumps(block))

        is_error = result.get("isError", False)
        text = "\n".join(text_parts)
        if is_error:
            return f"MCP Error: {text}"
        return text

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        self._request_id += 1
        req_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        await self._write_message(message)

        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"MCP request '{method}' timed out after 30s")

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write_message(message)

    async def _write_message(self, message: dict) -> None:
        """Write a JSON-RPC message to the server's stdin."""
        if not self._process or not self._process.stdin:
            raise RuntimeError(f"MCP server '{self.name}' is not running")

        data = json.dumps(message)
        self._process.stdin.write(data.encode() + b"\n")
        await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from the server's stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break  # EOF — process exited

                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("MCP '%s': invalid JSON: %s", self.name, line[:200])
                    continue

                # Handle response to a request
                if "id" in message and message["id"] in self._pending:
                    future = self._pending.pop(message["id"])
                    if "error" in message:
                        err = message["error"]
                        future.set_exception(
                            RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
                        )
                    else:
                        future.set_result(message.get("result", {}))

                # Handle notifications from server (log them)
                elif "method" in message and "id" not in message:
                    logger.debug("MCP '%s' notification: %s", self.name, message["method"])

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("MCP '%s' reader error: %s", self.name, e)

    async def _drain_stderr(self) -> None:
        """Read and log stderr to prevent pipe buffer deadlock."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.debug("MCP '%s' stderr: %s", self.name, line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("MCP '%s' stderr reader error: %s", self.name, e)


async def connect_mcp_servers(
    servers: list[dict],
    registry: ToolRegistry,
) -> list[MCPClient]:
    """Connect to configured MCP servers and register their tools.

    Args:
        servers: List of server configs, each with 'name', 'command', and optional 'env'.
        registry: The tool registry to register discovered tools into.

    Returns:
        List of connected MCPClient instances (caller should stop them on shutdown).
    """
    clients: list[MCPClient] = []

    for server_config in servers:
        name = server_config["name"]
        command = server_config["command"]
        env = server_config.get("env")

        client = MCPClient(name=name, command=command, env=env)
        try:
            await client.start()
            tools = await client.list_tools()
            logger.info("MCP '%s': discovered %d tools", name, len(tools))

            # Register each MCP tool into Mako's registry
            for tool in tools:
                tool_name = f"mcp_{name}_{tool['name']}"
                description = tool.get("description", f"MCP tool from {name}")
                input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})

                # Create a closure to capture the client and original tool name
                def make_handler(c: MCPClient, tn: str):
                    async def handler(**kwargs: Any) -> str:
                        return await c.call_tool(tn, kwargs)
                    return handler

                registry.register(
                    name=tool_name,
                    description=f"[MCP:{name}] {description}",
                    parameters=input_schema,
                    handler=make_handler(client, tool["name"]),
                )
                logger.info("  Registered tool: %s", tool_name)

            clients.append(client)

        except Exception as e:
            logger.error("Failed to connect MCP server '%s': %s", name, e)
            await client.stop()

    return clients
