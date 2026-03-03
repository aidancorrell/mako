# Mako - AI Agent Framework

## Project Overview

Mako is a minimal (~2,500 lines) Python AI agent framework built from scratch as a learning exercise. It implements a ReAct (Reason + Act) agent loop that can run locally via CLI or as a Telegram bot with scheduled cron jobs. Security is the foundation — the `SecurityGuard` was built first and gates every tool call before execution.

## Architecture

The system follows a layered architecture with clear separation of concerns:

```
Channels (CLI, Telegram, Scheduler)
    ↓
Agent Loop (ReAct: reason → act → observe → repeat)
    ↓
Context Assembler (system prompt + personality + memory + history)
    ↓
LLM Provider (Gemini or Claude)
    ↓ (tool calls)
SecurityGuard (validates every call)
    ↓
Tool Registry → Tool Execution → Result fed back to agent loop
```

### Core Flow

1. Channel receives user input
2. `ContextAssembler` builds messages (system prompt from `SOUL.md`/`IDENTITY.md`/`MEMORY.md` + conversation history)
3. `Agent.run()` sends messages to the LLM provider with tool schemas
4. If LLM returns tool calls → `SecurityGuard.pre_tool_call()` validates → `ToolRegistry.execute()` runs → result appended → loop
5. If LLM returns text → return as final response
6. `ContextCompactor` auto-summarizes old messages when approaching token limits

## Project Structure

```
src/mako/
├── __init__.py          # Version: 0.1.0
├── __main__.py          # `python -m mako` entry point
├── main.py              # Wires all components together, entry point
├── agent.py             # ReAct agent loop (~110 lines, the core)
├── config.py            # Pydantic settings from MAKO_* env vars
├── context.py           # Assembles system prompt + personality + memory
├── security.py          # SecurityGuard — gates every tool call
├── scheduler.py         # Cron job scheduler (timezone-aware)
├── providers/
│   ├── base.py          # Abstract Provider interface, Message/ToolCall dataclasses
│   ├── gemini.py        # Google Gemini via REST API (httpx)
│   └── claude.py        # Anthropic Claude via official SDK
├── channels/
│   ├── cli.py           # Terminal REPL with /new, /history commands
│   └── telegram.py      # Telegram bot (long-polling, per-chat sessions)
├── tools/
│   ├── registry.py      # Tool registration, JSON Schema generation, execution
│   ├── web_fetch.py     # Fetch URLs (HTTPS-only, SSRF-protected)
│   ├── shell.py         # Allowlisted shell commands via exec (not shell)
│   ├── workspace.py     # Read/write files within workspace jail
│   └── mcp.py           # MCP client (JSON-RPC 2.0 over stdio)
└── memory/
    ├── store.py         # SQLite conversation history (WAL mode)
    ├── workspace.py     # Loads personality/memory markdown files from workspace/
    └── compactor.py     # Auto-summarizes old messages at token limit

workspace/               # Agent's sandboxed file workspace
├── SOUL.md              # Personality definition (read-only to agent)
├── IDENTITY.md          # Identity/purpose (read-only to agent)
└── MEMORY.md            # Persistent knowledge (read-only to agent)

tests/                   # Test suite (run with: uv run pytest)
docs/
└── architecture.mmd     # Mermaid flowchart diagram
```

### Key Data Directories (created at runtime, not in git)

- `data/` — SQLite database (`conversations.db`)
- `audit/` — Audit log (`audit.log`, stored outside workspace so agent can't tamper)

## Key Modules

### `agent.py` — The ReAct Loop
The heart of the framework. Loops up to `max_iterations` (default 10): sends context to the LLM, processes any tool calls through SecurityGuard, feeds results back, repeats until the LLM returns a text response.

### `security.py` — SecurityGuard
Gates **every** tool call. Implements:
- **Command allowlist**: Shell tool only runs commands in `MAKO_SAFE_BINS_STR` (default: `date`)
- **Shell metacharacter rejection**: Blocks `|;&$(){}!\n\r\x00#><` — no pipes, chains, or redirects
- **Workspace jail**: File paths resolved via `.resolve()`, must be within `workspace_path`
- **SSRF protection**: HTTPS-only, port 443, DNS-resolved IPs checked against private/reserved ranges
- **Protected files**: `SOUL.md`, `IDENTITY.md`, `MEMORY.md`, and `memory/*` are write-blocked (case-insensitive, traversal-resistant)
- **Rate limiting**: Per-session scoped (20/turn, 30/minute)
- **Loop detection**: Hard cap on iterations per agent turn
- **Audit logging**: JSON log outside workspace, truncates large values
- **MCP sandboxing**: Subprocess env sanitized, path args validated

### `config.py` — Settings
All config via environment variables with `MAKO_` prefix, loaded by `pydantic-settings`. See `.env.example` for the full list. Key settings:
- `MAKO_DEFAULT_PROVIDER` — `"gemini"` (default) or `"claude"`
- `MAKO_SAFE_BINS_STR` — Comma-separated allowlisted shell commands
- `MAKO_WORKSPACE_PATH` — Workspace directory (default: `workspace`)
- `MAKO_MAX_ITERATIONS` — Agent loop cap (default: 10)
- `MAKO_CONTEXT_LIMIT_TOKENS` / `MAKO_COMPACTION_TRIGGER_RATIO` — Context compaction thresholds

### `providers/` — LLM Providers
Abstract `Provider` interface with two implementations:
- **GeminiProvider**: Raw REST API calls via httpx to `generativelanguage.googleapis.com`
- **ClaudeProvider**: Uses the official `anthropic` SDK (`AsyncAnthropic`)

Both convert between the internal `Message`/`ToolCall` dataclasses and provider-specific formats.

### `tools/` — Tool System
Tools are registered with `ToolRegistry` and expose JSON Schema definitions to the LLM:
- `web_fetch(url)` — Fetches HTTPS URLs, strips HTML, truncates to 8000 chars
- `shell(command)` — Runs allowlisted commands via `create_subprocess_exec` (30s timeout)
- `read_file(path)` / `write_file(path, content)` — Workspace-jailed file I/O
- `mcp_*` — Dynamically registered from MCP servers (named `mcp_{server}_{tool}`)

### `memory/` — Persistence
- **ConversationStore**: SQLite with WAL mode, sessions + messages tables
- **Workspace loader**: Reads `SOUL.md`, `IDENTITY.md`, `MEMORY.md`, and `memory/*.md` with size caps (50KB/file, 200KB total)
- **ContextCompactor**: When token count exceeds 75% of limit, summarizes older messages via the LLM, keeping the most recent 10

### `channels/` — I/O Channels
- **CLI**: Async REPL with `/new` and `/history` commands, in-memory history trimmed to 30 messages
- **Telegram**: Long-polling bot with per-chat sessions, chat allowlist enforcement, typing indicators, message splitting at 4096 chars

### `scheduler.py` — Cron Jobs
Timezone-aware cron scheduler. Configured via `jobs.json` (see `jobs.json.example`). Checks every 60 seconds, runs agent with the job's prompt, delivers results via Telegram bot. Supports standard 5-field cron with ranges, steps, and comma-separated values.

## Security Model — Critical Design Decisions

These are **intentional** security constraints. Do not weaken or bypass them:

1. **Deny-by-default**: No tool runs unless explicitly allowed through SecurityGuard
2. **No shell interpretation**: Commands run via `create_subprocess_exec`, never `create_subprocess_shell`
3. **curl excluded from allowlist**: Use `web_fetch` which has SSRF protections
4. **Workspace jail enforced via `.resolve()`**: Follows symlinks before checking boundaries
5. **Protected files are case-insensitive**: `soul.md`, `SOUL.MD`, etc. all blocked from writes
6. **MCP config must be outside workspace**: Prevents the agent from modifying its own tool access
7. **Audit log outside workspace**: Agent cannot read or tamper with its own audit trail
8. **Telegram requires allowlist**: Fail-closed — won't start without `MAKO_TELEGRAM_ALLOWED_CHAT_IDS_STR`
9. **Context compaction strips prompt injection**: Summarizer is told to strip directives from conversation
10. **MCP subprocess env sanitized**: Only essential system vars inherited, no API keys leaked

## Development

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup
```bash
uv sync                    # Install dependencies
cp .env.example .env       # Configure API keys
```

### Running
```bash
uv run mako                # CLI mode (default)
uv run mako --telegram     # Telegram bot mode
uv run mako --debug        # Debug logging (verbose)
```

### Testing
```bash
uv run pytest              # Run test suite
```

### Docker Deployment
```bash
# Development
docker compose up -d

# Production (hardened container: read-only rootfs, non-root, all caps dropped, 256MB RAM)
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

## Tech Stack & Dependencies

- **Python 3.12+** with asyncio
- **httpx** — Async HTTP client (used by Gemini provider and web_fetch tool)
- **pydantic / pydantic-settings** — Settings and data validation
- **anthropic** — Official Anthropic SDK (Claude provider)
- **python-telegram-bot** — Telegram bot framework
- **SQLite** (stdlib) — Conversation persistence with WAL mode
- **uv** — Package manager and build tool
- **Docker** — Production deployment with multi-stage build

No heavy frameworks — raw implementations for learning purposes.

## Code Conventions

- **Async throughout**: All I/O operations use `async`/`await`
- **Dataclasses for data**: `Message`, `ToolCall`, `Job` are `@dataclass`
- **Pydantic for validation**: `Settings` uses `pydantic-settings` with env var binding
- **Logging via stdlib**: Each module has `logger = logging.getLogger(__name__)`
- **Type hints everywhere**: Full type annotations on all function signatures
- **Docstrings**: Module-level and class-level docstrings describe purpose and design rationale
- **Constants at module level**: `MAX_CONTENT_LENGTH`, `TOOL_NAME`, etc.
- **Security checks before execution**: Never trust, always validate
- **Tool handlers are async functions**: Return `str` results, registered via `ToolRegistry.register()`

## Adding New Components

### Adding a New Tool
1. Create `src/mako/tools/your_tool.py` with `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_PARAMETERS` (JSON Schema), and an `async def handler(**kwargs) -> str`
2. Register in `main.py:create_agent()` via `registry.register()`
3. Add any needed security validation in `SecurityGuard.pre_tool_call()`

### Adding a New Provider
1. Create `src/mako/providers/your_provider.py` implementing the `Provider` ABC
2. Implement `name` property and `async chat(messages, tools)` method
3. Add provider creation logic in `main.py:create_provider()`
4. Add config fields in `config.py:Settings`

### Adding a New Channel
1. Create `src/mako/channels/your_channel.py`
2. Accept `Agent` and `ConversationStore` as dependencies
3. Wire up in `main.py:async_main()`

## Important Files Outside Source

| File | Purpose |
|---|---|
| `.env.example` | Template for all environment variables |
| `jobs.json.example` | Template for scheduled cron jobs |
| `mcp_servers.example.json` | Template for MCP server configuration |
| `workspace/SOUL.md` | Agent personality definition |
| `workspace/IDENTITY.md` | Agent identity/purpose |
| `workspace/MEMORY.md` | Agent persistent knowledge |
| `docs/architecture.mmd` | Mermaid architecture diagram |
| `Dockerfile` | Multi-stage production container |
| `docker-compose.prod.yml` | Hardened production deployment |
