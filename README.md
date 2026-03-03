# 🦈 Mako

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
│  │  shell (date)  │ │  over stdio  │ │  Markdown files  │      │
│  │  read_file     │ │              │ │  (SOUL, MEMORY)  │      │
│  │  write_file    │ │  Connects to │ │  Context         │      │
│  │  (workspace    │ │  any MCP     │ │   compaction     │      │
│  │   jailed)      │ │  server      │ │  (auto-summary)  │      │
│  └────────────────┘ └──────────────┘ └──────────────────┘      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    SecurityGuard                          │   │
│  │                                                          │   │
│  │  Command allowlist ─ date only (curl removed for SSRF)   │   │
│  │  Metacharacter rejection ─ no pipes, chains, subshells   │   │
│  │  Workspace jail ─ file ops can't escape workspace/       │   │
│  │  Protected files ─ SOUL/IDENTITY/MEMORY read-only        │   │
│  │  SSRF protection ─ HTTPS-only, private IP blocking       │   │
│  │  Rate limiting ─ 20/turn, 30/minute (per-session)        │   │
│  │  Loop detection ─ max 10 iterations                      │   │
│  │  Audit log ─ every tool call logged (outside workspace)  │   │
│  │  MCP sandboxing ─ sanitized env, path validation         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

Deployment (Oracle Cloud ARM VPS):
┌──────────────────────────────────────────┐
│  Docker Container                        │
│  read-only rootfs, non-root user (1003)  │
│  no-new-privileges, all caps dropped     │
│  256MB RAM / 0.5 CPU limit               │
│  Volumes: workspace/ + data/ + audit/    │
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
| `MAKO_TELEGRAM_ALLOWED_CHAT_IDS_STR` | Comma-separated allowed chat IDs | (required for Telegram mode) |
| `MAKO_SAFE_BINS_STR` | Allowed shell commands | `date` |
| `MAKO_MAX_ITERATIONS` | Max agent loop iterations | `10` |
| `MAKO_CONTEXT_LIMIT_TOKENS` | Context window token limit | `200000` |
| `MAKO_COMPACTION_TRIGGER_RATIO` | Compact when context exceeds this ratio | `0.75` |

### MCP Servers

Configure MCP servers in `mcp_servers.json` (must be outside the workspace directory):

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
- **Command allowlist** — shell only runs `date` by default; `curl` intentionally excluded (use `web_fetch` which has SSRF protections)
- **SSRF protection** — HTTPS-only, port 443, DNS resolution validates all IPs against private/reserved ranges, redirect hops re-validated
- **Workspace jail** — file operations resolve symlinks and reject anything outside `workspace/`
- **Protected files** — `SOUL.md`, `IDENTITY.md`, `MEMORY.md`, and `memory/` are read-only (case-insensitive, path-traversal resistant)
- **Rate limiting** — per-session scoping prevents cross-chat interference (20/turn, 30/minute)
- **Loop detection** — hard cap of 10 agent iterations per turn
- **Prompt injection defense** — system prompt marks tool results as untrusted; compaction strips directives; personality files protected from writes
- **Audit log** — every tool invocation logged outside the workspace (tamper-resistant), args truncated
- **MCP sandboxing** — config must be outside workspace, subprocess env sanitized (no API key leakage), path args validated
- **Telegram allowlist** — required in Telegram mode (fail-closed, not fail-open)
- **Container hardening** — read-only rootfs, non-root user, all capabilities dropped, memory/CPU limits, no-new-privileges
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
