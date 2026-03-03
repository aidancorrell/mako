# 🦈 Mako

A minimal AI agent framework built from scratch in ~2,500 lines of Python.

Mako is a personal AI agent accessible via Telegram or CLI. It's designed as a learning exercise — small enough to read end-to-end and fully understand, with security baked in from line 1.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                              Mako                                   │
│                                                                     │
│  Channels              Scheduler                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                          │
│  │   CLI    │  │ Telegram │  │   Cron   │                          │
│  │   REPL   │  │   Bot    │  │  Jobs    │                          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                          │
│       └──────────────┼─────────────┘                                │
│                      ▼                                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Agent Loop (ReAct)                        │   │
│  │                                                              │   │
│  │   ┌────────────┐       ┌────────────────────────────┐        │   │
│  │   │  Context    │       │      LLM Providers         │        │   │
│  │   │  Assembler  │──────▶│  Gemini Flash │ Claude     │        │   │
│  │   │            │       └───────────┬────────────────┘        │   │
│  │   │ SOUL.md    │                   │                          │   │
│  │   │ MEMORY.md  │                   ▼                          │   │
│  │   │ History    │       ┌────────────────────┐                 │   │
│  │   └────────────┘       │   Tool calls?      │                 │   │
│  │                        └───┬────────────┬───┘                 │   │
│  │                        No  │            │ Yes                  │   │
│  │                            ▼            ▼                     │   │
│  │                       Response   ┌──────────────┐             │   │
│  │                                  │ SecurityGuard│             │   │
│  │                                  │  (validate)  │             │   │
│  │                                  └──────┬───────┘             │   │
│  │                                         ▼                     │   │
│  │                                  ┌──────────────┐             │   │
│  │                                  │ Execute Tool │◀──┐         │   │
│  │                                  └──────────────┘   │         │   │
│  │                                         │     (loop)│         │   │
│  │                                         └───────────┘         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Tools                          Memory                              │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐     │
│  │ web_fetch (SSRF-    │  │ SQLite history (WAL mode)        │     │
│  │   protected)        │  │ Markdown personality files       │     │
│  │ shell (allowlisted) │  │ Context compaction (auto-summary │     │
│  │ read/write file     │  │   when approaching token limit)  │     │
│  │   (workspace jail)  │  └──────────────────────────────────┘     │
│  │ MCP client (any     │                                           │
│  │   MCP server)       │                                           │
│  └─────────────────────┘                                           │
│                                                                     │
│  SecurityGuard (gates every tool call)                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Command allowlist    │ SSRF protection    │ Rate limiting    │   │
│  │ Workspace jail       │ Protected files    │ Loop detection   │   │
│  │ Metachar rejection   │ MCP sandboxing     │ Audit logging    │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

Docker Deployment:
┌──────────────────────────────────────────────┐
│  Container: read-only rootfs, non-root user  │
│  no-new-privileges, all capabilities dropped │
│  256MB RAM / 0.5 CPU, tmpfs /tmp only        │
│  Volumes: workspace/ + data/ + audit/        │
│  Network: DNS + HTTP + HTTPS only            │
└──────────────────────────────────────────────┘
```

## Project Structure

```
src/mako/
├── main.py              # Entry point, wires everything together
├── config.py            # Pydantic settings from env vars
├── agent.py             # ReAct loop — the core (~50 lines)
├── context.py           # Context assembly (personality + memory + history)
├── security.py          # SecurityGuard — gates every tool call
├── scheduler.py         # Cron job scheduler (timezone-aware)
├── providers/
│   ├── base.py          # Abstract provider interface
│   ├── gemini.py        # Google Gemini via REST API
│   └── claude.py        # Anthropic Claude via SDK
├── channels/
│   ├── cli.py           # Terminal REPL
│   └── telegram.py      # Telegram bot (long-polling)
├── tools/
│   ├── registry.py      # Tool registry + JSON Schema generation
│   ├── web_fetch.py     # Fetch URLs (HTTPS, SSRF-protected)
│   ├── shell.py         # Allowlisted commands via exec (not shell)
│   ├── workspace.py     # Read/write files in workspace jail
│   └── mcp.py           # MCP client (JSON-RPC over stdio)
└── memory/
    ├── store.py          # SQLite conversation history (WAL mode)
    ├── workspace.py      # Load personality/memory markdown files
    └── compactor.py      # Context compaction (auto-summarize old messages)
```

## Quick Start

```bash
# Install dependencies
uv sync

# Configure (copy and edit)
cp .env.example .env

# Run CLI mode
uv run mako

# Run Telegram bot (with scheduled jobs)
uv run mako --telegram

# Debug mode
uv run mako --debug
```

## Configuration

All settings via environment variables (prefix `MAKO_`):

| Variable | Description | Default |
|---|---|---|
| `MAKO_GEMINI_API_KEY` | Google Gemini API key | |
| `MAKO_ANTHROPIC_API_KEY` | Anthropic API key | |
| `MAKO_DEFAULT_PROVIDER` | `gemini` or `claude` | `gemini` |
| `MAKO_TELEGRAM_BOT_TOKEN` | Telegram bot token | |
| `MAKO_TELEGRAM_ALLOWED_CHAT_IDS_STR` | Comma-separated allowed chat IDs | (required for Telegram) |
| `MAKO_SAFE_BINS_STR` | Allowed shell commands | `date` |
| `MAKO_MAX_ITERATIONS` | Max agent loop iterations | `10` |
| `MAKO_CONTEXT_LIMIT_TOKENS` | Context window token limit | `200000` |
| `MAKO_COMPACTION_TRIGGER_RATIO` | Compact when context exceeds ratio | `0.75` |

### MCP Servers

Connect to any [MCP](https://modelcontextprotocol.io/) server. Configure in `mcp_servers.json`:

```json
[
    {
        "name": "filesystem",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp/sandbox"]
    }
]
```

### Scheduled Jobs

Run prompts on a cron schedule, delivered via Telegram. Configure in `jobs.json` (see `jobs.json.example`):

```json
{
  "jobs": [
    {
      "name": "daily-briefing",
      "enabled": true,
      "cron": "0 8 * * *",
      "tz": "America/New_York",
      "chat_id": 123456789,
      "timeout_seconds": 300,
      "prompt": "Your prompt here..."
    }
  ]
}
```

## Security

Security is the foundation, not a bolt-on. The `SecurityGuard` module was built first and gates every tool call:

- **Deny by default** — no tool runs unless explicitly allowed
- **Command allowlist** — shell only runs allowlisted commands; `curl` intentionally excluded (use `web_fetch` with SSRF protections)
- **SSRF protection** — HTTPS-only, port 443, all resolved IPs validated against private/reserved ranges, redirect hops re-validated
- **Workspace jail** — file operations resolve symlinks and reject anything outside `workspace/`
- **Protected files** — personality/memory files are read-only (case-insensitive, path-traversal resistant)
- **Rate limiting** — per-session scoping prevents cross-chat interference (20/turn, 30/minute)
- **Loop detection** — hard cap on agent iterations per turn
- **Prompt injection defense** — tool results marked untrusted; compaction strips directives; personality files immutable
- **Audit log** — every tool invocation logged outside the workspace (tamper-resistant)
- **MCP sandboxing** — subprocess env sanitized (no API key leakage), path args validated
- **Telegram allowlist** — required in Telegram mode (fail-closed)
- **Container hardening** — read-only rootfs, non-root user, all capabilities dropped, memory/CPU limits, no-new-privileges

## Deployment

```bash
# Production (hardened container)
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f

# Update
git pull && docker compose -f docker-compose.prod.yml up -d --build
```

## Why Build This?

Most AI agent frameworks are massive — tens or hundreds of thousands of lines, with layers of abstraction that make it hard to understand what's actually happening. Mako exists to answer: **what's the minimum you actually need?**

The answer is ~2,500 lines of Python: a ReAct loop, a provider abstraction, a tool registry, a security layer, and some I/O channels. No plugins, no skill registries, no complex dependency graphs. Just the core primitives, readable end-to-end in an afternoon.

Building it from scratch also means security is the foundation rather than a bolt-on. Every tool call passes through the SecurityGuard before execution — command allowlists, workspace jailing, SSRF protection, rate limiting, and full audit logging are baked in from line 1.

## Tech Stack

- Python 3.12, asyncio, httpx
- pydantic / pydantic-settings
- python-telegram-bot
- anthropic SDK
- SQLite (stdlib)
- Docker, uv
