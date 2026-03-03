# Mako

A minimal AI agent framework built from scratch in ~2,500 lines of Python.

Mako is a personal AI agent that runs on an Oracle Cloud ARM VPS, accessible via Telegram. It's designed as a learning exercise — small enough to read end-to-end and fully understand, with security baked in from line 1.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           Mako                                  │
│                                                                 │
│  ┌───────────┐  ┌───────────┐                                  │
│  │    CLI     │  │ Telegram  │  Channels                        │
│  │   REPL    │  │   Bot     │  (input/output)                  │
│  └─────┬─────┘  └─────┬─────┘                                  │
│        │              │                                         │
│        └──────┬───────┘                                         │
│               ▼                                                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │                    Agent Loop (ReAct)                   │     │
│  │                                                        │     │
│  │  User message                                          │     │
│  │       │                                                │     │
│  │       ▼                                                │     │
│  │  ┌──────────────┐    ┌──────────────────────────────┐  │     │
│  │  │   Context     │    │       Providers              │  │     │
│  │  │  Assembler    │───▶│  ┌─────────┐ ┌───────────┐  │  │     │
│  │  │              │    │  │ Gemini  │ │  Claude   │  │  │     │
│  │  │ SOUL.md      │    │  │  Flash  │ │  Sonnet   │  │  │     │
│  │  │ IDENTITY.md  │    │  └─────────┘ └───────────┘  │  │     │
│  │  │ MEMORY.md    │    └──────────────┬───────────────┘  │     │
│  │  │ History      │                   │                  │     │
│  │  └──────────────┘                   ▼                  │     │
│  │                          ┌──────────────────┐          │     │
│  │                          │  Tool calls?     │          │     │
│  │                          └────┬────────┬────┘          │     │
│  │                          No   │        │ Yes           │     │
│  │                               ▼        ▼              │     │
│  │                          Response  ┌────────────┐      │     │
│  │                                    │  Security  │      │     │
│  │                                    │   Guard    │      │     │
│  │                                    └─────┬──────┘      │     │
│  │                                          ▼             │     │
│  │                                    ┌────────────┐      │     │
│  │                                    │  Execute   │      │     │
│  │                                    │   Tool     │──┐   │     │
│  │                                    └────────────┘  │   │     │
│  │                                          ▲         │   │     │
│  │                                          └─────────┘   │     │
│  │                                        (loop back)     │     │
│  └────────────────────────────────────────────────────────┘     │
│                               │                                 │
│               ┌───────────────┼───────────────┐                 │
│               ▼               ▼               ▼                 │
│  ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐      │
│  │  Built-in Tools │ │  MCP Client  │ │     Memory       │      │
│  │                │ │              │ │                  │      │
│  │  web_fetch     │ │  JSON-RPC    │ │  SQLite history  │      │
│  │  shell (curl,  │ │  over stdio  │ │  Markdown files  │      │
│  │    date only)  │ │              │ │  (SOUL, MEMORY)  │      │
│  │  read_file     │ │  Connects to │ │                  │      │
│  │  write_file    │ │  any MCP     │ └──────────────────┘      │
│  │  (workspace    │ │  server      │                            │
│  │   jailed)      │ └──────────────┘                            │
│  └────────────────┘                                             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    SecurityGuard                          │   │
│  │                                                          │   │
│  │  Command allowlist ─ only curl, date                     │   │
│  │  Metacharacter rejection ─ no pipes, chains, subshells   │   │
│  │  Workspace jail ─ file ops can't escape workspace/       │   │
│  │  Rate limiting ─ 20/turn, 30/minute                      │   │
│  │  Loop detection ─ max 10 iterations                      │   │
│  │  Audit log ─ every tool call logged                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

Deployment (Oracle Cloud ARM VPS):
┌──────────────────────────────────────────┐
│  Docker Container                        │
│  read-only rootfs, non-root user (1003)  │
│  no-new-privileges, dropped caps         │
│  256MB RAM / 0.5 CPU limit               │
│  Volumes: workspace/ + data/             │
├──────────────────────────────────────────┤
│  iptables: DNS(53) HTTP(80) HTTPS(443)   │
│  Everything else → DROP                  │
├──────────────────────────────────────────┤
│  Secrets: /opt/mako.env (root:mako 640)  │
└──────────────────────────────────────────┘
```

## Project Structure

```
src/mako/
├── main.py              # Entry point, wires everything together
├── config.py            # Pydantic settings from env vars
├── agent.py             # ReAct loop — the core
├── context.py           # Context assembly (personality + memory + history)
├── security.py          # SecurityGuard — gates every tool call
├── providers/
│   ├── base.py          # Abstract provider interface
│   ├── gemini.py        # Google Gemini via REST API
│   └── claude.py        # Anthropic Claude via SDK
├── channels/
│   ├── cli.py           # Terminal REPL
│   └── telegram.py      # Telegram bot (long-polling)
├── tools/
│   ├── registry.py      # Tool registry + JSON Schema generation
│   ├── web_fetch.py     # Fetch URLs, strip HTML
│   ├── shell.py         # Allowlisted commands via exec (not shell)
│   ├── workspace.py     # Read/write files in workspace jail
│   └── mcp.py           # MCP client (JSON-RPC over stdio)
└── memory/
    ├── store.py          # SQLite conversation history
    └── workspace.py      # Load personality/memory markdown files
```

## Quick Start

```bash
# Install dependencies
uv sync

# Configure (copy and edit)
cp .env.example .env

# Run CLI mode
uv run mako

# Run Telegram bot
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
| `MAKO_TELEGRAM_ALLOWED_CHAT_IDS_STR` | Comma-separated allowed chat IDs | |
| `MAKO_SAFE_BINS_STR` | Allowed shell commands | `curl,date` |
| `MAKO_MAX_ITERATIONS` | Max agent loop iterations | `10` |

### MCP Servers

Configure MCP servers in `mcp_servers.json`:

```json
[
    {
        "name": "filesystem",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp/sandbox"]
    }
]
```

## Security

Security is the foundation, not a bolt-on:

- **Deny by default** — no tool runs unless explicitly allowed
- **Command allowlist** — shell only runs `curl` and `date`, metacharacters rejected, executed via `exec` not `shell`
- **Workspace jail** — file operations resolve symlinks and reject anything outside `workspace/`
- **Rate limiting** — max 20 tool calls per turn, 30 per minute
- **Loop detection** — hard cap of 10 agent iterations per turn
- **Audit log** — every tool invocation logged with timestamp, tool, args, result, and LLM reasoning
- **Container hardening** — read-only rootfs, non-root user, dropped capabilities, memory/CPU limits, no-new-privileges
- **Network restriction** — iptables allows only DNS, HTTP, HTTPS outbound

## Deployment

Runs as a Docker container on an Oracle Cloud ARM VPS:

```bash
# Production (hardened)
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f

# Update
git pull && docker compose -f docker-compose.prod.yml up -d --build
```

## Tech Stack

- Python 3.12, asyncio, httpx
- pydantic / pydantic-settings
- python-telegram-bot
- anthropic SDK
- SQLite (stdlib)
- Docker, uv
