"""Entry point for Mako."""

import asyncio
import logging
import sys
from pathlib import Path

from mako.agent import Agent
from mako.channels.cli import run_cli
from mako.config import load_mcp_servers, load_settings
from mako.scheduler import Scheduler, load_jobs
from mako.context import ContextAssembler
from mako.memory.store import ConversationStore
from mako.providers.base import Provider
from mako.security import SecurityGuard
from mako.tools import shell, web_fetch, workspace
from mako.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    level = logging.DEBUG if "--debug" in sys.argv else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def create_provider(settings) -> Provider:
    """Create the configured LLM provider."""
    if settings.default_provider == "claude":
        if not settings.anthropic_api_key:
            print("Error: MAKO_ANTHROPIC_API_KEY not set")
            sys.exit(1)
        from mako.providers.claude import ClaudeProvider
        return ClaudeProvider(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            web_search=settings.claude_web_search,
            max_pause_continuations=settings.claude_max_pause_continuations,
            max_retries=settings.claude_max_retries,
            retry_base_delay=settings.claude_retry_base_delay,
        )
    else:
        if not settings.gemini_api_key:
            print("Error: MAKO_GEMINI_API_KEY not set")
            sys.exit(1)
        from mako.providers.gemini import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )


def create_agent(settings) -> tuple[Agent, ConversationStore, ToolRegistry]:
    """Wire up all components and create the agent."""
    # Security — the foundation
    security = SecurityGuard(
        workspace_path=settings.workspace_path,
        safe_bins=settings.safe_bins,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        max_tool_calls_per_minute=settings.max_tool_calls_per_minute,
        max_iterations=settings.max_iterations,
    )

    # Provider
    provider = create_provider(settings)

    # Context assembler (personality + memory)
    context = ContextAssembler(settings.workspace_path)

    # Tool registry
    registry = ToolRegistry(security)

    # Wire settings into tools
    shell._security = security
    shell._max_output_length = settings.max_shell_output_length
    web_fetch._max_content_length = settings.max_web_fetch_content_length
    web_fetch._max_response_bytes = settings.max_web_fetch_response_bytes

    # Register built-in tools
    registry.register(
        name=web_fetch.TOOL_NAME,
        description=web_fetch.TOOL_DESCRIPTION,
        parameters=web_fetch.TOOL_PARAMETERS,
        handler=web_fetch.web_fetch,
    )
    registry.register(
        name=shell.TOOL_NAME,
        description=shell.TOOL_DESCRIPTION,
        parameters=shell.TOOL_PARAMETERS,
        handler=shell.shell,
    )
    workspace.register_workspace_tools(registry, settings.workspace_path)

    # Conversation store (SQLite)
    data_dir = settings.workspace_path.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    store = ConversationStore(data_dir / "conversations.db")

    agent = Agent(
        provider=provider,
        registry=registry,
        security=security,
        settings=settings,
        context=context,
    )

    return agent, store, registry


async def connect_mcp(settings, registry: ToolRegistry) -> list:
    """Connect to configured MCP servers and register their tools."""
    # Ensure MCP config is not inside the workspace (writable by the agent)
    mcp_path = settings.mcp_config_path.resolve()
    workspace_resolved = settings.workspace_path.resolve()
    try:
        mcp_path.relative_to(workspace_resolved)
        logger.warning(
            "MCP config '%s' is inside workspace — ignoring for security. "
            "Move it outside the workspace directory.",
            mcp_path,
        )
        return []
    except ValueError:
        pass  # Good — it's outside the workspace

    servers = load_mcp_servers(settings.mcp_config_path)
    if not servers:
        return []

    from mako.tools.mcp import connect_mcp_servers
    clients, failed = await connect_mcp_servers(servers, registry)
    if failed:
        logger.warning(
            "MCP servers failed to start: %s — their tools are unavailable",
            ", ".join(failed),
        )
    return clients


async def run_telegram_mode(agent: Agent, store: ConversationStore, settings) -> None:
    """Run Mako in Telegram bot mode."""
    if not settings.telegram_bot_token:
        print("Error: MAKO_TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    from mako.channels.telegram import TelegramChannel

    allowed = settings.telegram_allowed_chat_ids
    if not allowed:
        print(
            "Error: MAKO_TELEGRAM_ALLOWED_CHAT_IDS_STR not set. "
            "Refusing to start Telegram bot without an allowlist."
        )
        sys.exit(1)

    channel = TelegramChannel(
        token=settings.telegram_bot_token,
        agent=agent,
        store=store,
        allowed_chat_ids=allowed,
        context=agent.context,
    )

    await channel.run()

    # Start scheduler for cron jobs (uses the bot to deliver messages)
    jobs = load_jobs(settings.jobs_config_path)
    scheduler = Scheduler(
        jobs=jobs,
        agent=agent,
        bot=channel._app.bot,
        store=store,
    )
    await scheduler.start()

    # Keep running until interrupted
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await scheduler.stop()
        await channel.stop()


async def async_main() -> None:
    setup_logging()
    settings = load_settings()
    agent, store, registry = create_agent(settings)

    # Connect MCP servers (if configured)
    mcp_clients = await connect_mcp(settings, registry)

    try:
        if "--telegram" in sys.argv:
            await run_telegram_mode(agent, store, settings)
        else:
            await run_cli(agent, store)
    finally:
        # Clean up MCP servers
        for client in mcp_clients:
            await client.stop()
        store.close()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
