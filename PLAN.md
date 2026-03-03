# Mako - Build Your Own AI Agent Framework

## Context

You have OpenClaw running on an Oracle Cloud ARM VPS (Ubuntu 24.04, 2 OCPUs, 12GB RAM) delivering daily morning briefings to Telegram via Gemini 2.5 Flash. The goal is to build **Mako** — your own Python AI agent from scratch — as a learning exercise that runs alongside OpenClaw on the same VPS, with the potential to eventually replace it.

OpenClaw is 430K+ lines of TypeScript. Mako will be ~2-5K lines of Python — small enough to read end-to-end and fully understand.

## Architecture

```
┌──────────────────────────────────────────┐
│                  Mako                     │
├──────────────────────────────────────────┤
│  Channels                                │
│  ├─ CLI (local dev/testing)              │
│  └─ Telegram (python-telegram-bot)       │
├──────────────────────────────────────────┤
│  Gateway                                 │
│  └─ Message router + session manager     │
│  └─ Binds to 127.0.0.1 (loopback only)  │
├──────────────────────────────────────────┤
│  Agent Loop (ReAct)                      │
│  ├─ Context assembler (system prompt +   │
│  │   memory + tool defs + history)       │
│  ├─ Provider abstraction                 │
│  │   ├─ Gemini 2.5 Flash                │
│  │   └─ Claude Sonnet                   │
│  ├─ Tool call parser + executor          │
│  └─ Loop detection (max iterations)      │
├──────────────────────────────────────────┤
│  Tools                                   │
│  ├─ Built-in: web_fetch, shell (allowlist)│
│  ├─ Built-in: read/write workspace files │
│  └─ MCP client (Phase 5)                │
├──────────────────────────────────────────┤
│  Memory                                  │
│  ├─ SQLite (conversation history)        │
│  └─ Markdown files (SOUL.md, MEMORY.md)  │
├──────────────────────────────────────────┤
│  Security                                │
│  ├─ Command allowlist (like OpenClaw)    │
│  ├─ Workspace-scoped file access         │
│  ├─ Rate limiting                        │
│  └─ Audit log (every tool call logged)   │
├──────────────────────────────────────────┤
│  Scheduler                               │
│  └─ Cron-like jobs (morning briefing)    │
└──────────────────────────────────────────┘
```

## Tech Stack

- **Python 3.12+** (already available on Ubuntu 24.04)
- **asyncio + httpx** — async HTTP for LLM API calls and web fetching
- **python-telegram-bot** — async Telegram integration
- **sqlite3** (stdlib) — conversation history and memory
- **pydantic** — config validation and tool schema definitions
- **uv** — package management (fast, Rust-based)
- **No heavy frameworks** — raw implementation for learning

## Project Structure

```
mako/
├── pyproject.toml
├── CLAUDE.md
├── .env.example
├── Dockerfile                   # Multi-stage build, non-root user, minimal image
├── docker-compose.yml           # Dev environment
├── docker-compose.prod.yml      # Production (VPS) with security hardening
├── src/
│   └── mako/
│       ├── __init__.py
│       ├── main.py              # Entry point (CLI + Telegram modes)
│       ├── config.py            # Pydantic settings from env vars
│       ├── agent.py             # ReAct loop (the core)
│       ├── context.py           # Context assembly (history + memory + tools)
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py          # Abstract provider interface
│       │   ├── gemini.py        # Google Gemini API
│       │   └── claude.py        # Anthropic Claude API
│       ├── channels/
│       │   ├── __init__.py
│       │   ├── cli.py           # Terminal REPL channel
│       │   └── telegram.py      # Telegram bot channel
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py      # Tool registry + schema generation
│       │   ├── web_fetch.py     # HTTP fetching tool
│       │   ├── shell.py         # Allowlisted shell execution
│       │   └── workspace.py     # Read/write workspace files
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── store.py         # SQLite conversation history
│       │   └── workspace.py     # Markdown file memory (SOUL.md etc.)
│       ├── scheduler.py         # Cron-like job runner
│       └── security.py          # Allowlists, audit logging, rate limits
├── workspace/                   # Agent's workspace (SOUL.md, MEMORY.md, etc.)
│   ├── SOUL.md
│   ├── IDENTITY.md
│   └── memory/
├── jobs.json                    # Scheduled jobs config
└── tests/
    ├── conftest.py
    ├── test_agent.py
    └── test_tools.py
```

## Security Philosophy

Security is not a phase — it's the foundation. Inspired by your OpenClaw hardening work, Mako follows these principles from line 1:

- **Deny by default** — no tool runs unless explicitly allowed
- **Workspace jail** — all file operations resolve paths and reject anything outside the workspace (no `../` escapes, no symlink following)
- **Command allowlist** — shell tool only runs commands on the allowlist (like OpenClaw's `safeBins`)
- **Audit everything** — every tool invocation logged with timestamp, tool name, args, result, and the LLM reasoning that triggered it
- **Secrets never in code** — all credentials via env vars, loaded from root-owned file
- **Loop detection** — hard cap on agent iterations to prevent runaway execution
- **No elevated access** — Mako runs as unprivileged user, no sudo, no docker group
- **Container isolation** — Docker provides process/network/filesystem isolation as the outer security boundary. The application-level SecurityGuard is the inner boundary. Defense in depth.

These aren't bolted on later. The security module is built in Phase 1, Docker is part of Phase 1 scaffolding, and every tool must pass through both layers.

## Implementation Phases

### Phase 1: Core Agent Loop + Security Foundation + CLI ✅ COMPLETE
**Goal:** Chat with Mako in your terminal, with security baked in from the start.

1. ✅ Set up project scaffolding with `uv init`
2. ✅ Implement `config.py` — load settings from env vars via pydantic-settings
3. ✅ **Implement `security.py` FIRST** — this gates everything else:
   - `SecurityGuard` class that validates every tool call before execution
   - Command allowlist (`safe_bins: list[str]` — start with `curl`, `date`)
   - Path resolver that jails file access to workspace dir (resolves symlinks, rejects `../`)
   - Audit logger: every tool call → append to `workspace/audit.log` with timestamp, tool, args, result
   - Rate limiter: max N tool calls per turn, max M per minute
   - Loop detection: hard cap of 10 iterations per agent turn
4. ✅ Implement `providers/base.py` — abstract `Provider` protocol with `chat()` method
5. ✅ Implement `providers/gemini.py` — Gemini 2.5 Flash via REST API (httpx)
6. ✅ Implement `providers/claude.py` — Claude via Anthropic Python SDK
7. ✅ Implement `tools/registry.py` — tool registration with JSON Schema generation. Every tool execution passes through `SecurityGuard` before running.
8. ✅ Implement `tools/web_fetch.py` — first tool (fetch a URL, return markdown content)
9. ✅ Implement `tools/shell.py` — allowlisted shell execution (validated by SecurityGuard)
10. ✅ Implement `tools/workspace.py` — read/write files within workspace only (paths validated by SecurityGuard)
11. ✅ Implement `agent.py` — the ReAct loop
12. ✅ Implement `channels/cli.py` — async terminal REPL
13. ✅ Implement `main.py` — entry point that runs CLI mode

**Deliverable:** `uv run mako` starts a CLI chat. You can ask it questions, it can fetch web pages and run allowlisted commands. Every tool call is audit-logged. Blocked commands are rejected and logged.

### Phase 2: Memory + Personality ✅ COMPLETE
**Goal:** Mako remembers conversations and has a personality.

1. ✅ Implement `memory/store.py` — SQLite-backed conversation history
   - `save_message(session_id, role, content, tool_calls)`
   - `get_history(session_id, limit=50)`
   - `list_sessions()`
2. ✅ Implement `memory/workspace.py` — read SOUL.md, MEMORY.md, IDENTITY.md on startup
3. ✅ Implement `context.py` — assemble full context for each turn:
   - System prompt + SOUL.md personality
   - Conversation history from SQLite
   - Tool definitions from registry
4. ✅ Create initial workspace files (SOUL.md, IDENTITY.md, MEMORY.md) — Mako's personality
5. ✅ Updated `agent.py` to use `ContextAssembler`
6. ✅ Updated `cli.py` with persistent history + `/new` and `/history` commands
7. ✅ Updated `main.py` to wire `ConversationStore` and `ContextAssembler`

**Deliverable:** Mako has persistent memory across sessions and a personality defined by workspace markdown files.

### Phase 3: Telegram Channel ✅ COMPLETE
**Goal:** Message Mako on Telegram.

1. ✅ Implement `channels/telegram.py`:
   - python-telegram-bot (async, long-polling)
   - Message handler → agent.run() → send response
   - Per-chat session management with persistent SQLite history
   - Long message splitting (respects 4096 char limit, splits on newlines/spaces)
   - Chat ID allowlist for authorization
   - `/start` and `/new` commands
   - Typing indicator while agent thinks
2. ✅ Update `main.py` — `--telegram` flag runs Telegram bot mode
3. ✅ Created Telegram bot, configured token and chat ID allowlist

**Deliverable:** Message Mako on Telegram, get responses powered by Gemini or Claude.

### Phase 4: Scheduler + Morning Briefing ⏭️ SKIPPED
**Status:** Skipped for now — Gemini API quality insufficient for reliable scheduled jobs. Can revisit when switching to Claude as default provider.

### Phase 5: MCP Client (Innovation Phase) ✅ COMPLETE
**Goal:** Connect Mako to the MCP ecosystem.

1. ✅ Implement `tools/mcp.py` — MCP client (JSON-RPC 2.0 over stdio):
   - `MCPClient` class: spawns MCP server subprocess, manages lifecycle
   - Initialize handshake (protocolVersion 2024-11-05)
   - Discover tools via `tools/list`
   - Execute tool calls via `tools/call`, parse content blocks
   - Async reader task for JSON-RPC responses + server notifications
   - Timeout handling (30s per request)
2. ✅ `connect_mcp_servers()` — connects to all configured servers, registers tools into Mako's registry with `mcp_{server}_{tool}` naming
3. ✅ Updated `config.py` — `load_mcp_servers()` loads from `mcp_servers.json`
4. ✅ Updated `main.py` — MCP connection on startup, cleanup on shutdown
5. ✅ Created `mcp_servers.example.json` — example config

**Deliverable:** Mako can connect to any MCP server and use its tools natively.

### Phase 6: Deploy to VPS (Dockerized) ✅ COMPLETE
**Goal:** Mako runs as a containerized service alongside OpenClaw on the Oracle VPS.

1. ✅ **Dockerfile** (multi-stage, security-hardened):
   - Build stage: `python:3.12-slim` + uv to install deps
   - Runtime stage: `python:3.12-slim` with non-root user (UID 1003)
   - Only `curl` installed (allowlisted bin)
   - `HEALTHCHECK` for container monitoring
2. ✅ **docker-compose.prod.yml** — production config:
   - `read_only: true` root filesystem
   - `tmpfs` for `/tmp` only
   - Workspace + data volume mounts
   - `no-new-privileges: true`
   - Drop all capabilities, add back `NET_RAW`
   - Memory limit 256MB, CPU limit 0.5
   - Env file: `/opt/mako.env`
3. ✅ **docker-compose.yml** — dev config (relaxed for local testing)
4. ✅ **Shell command hardening** — metacharacter rejection + exec (not shell) execution
5. ✅ **Created `mako` user on VPS** (UID 1003, docker group)
6. ✅ **GitHub repo** — private at github.com/aidancorrell/mako, deploy key on VPS
7. ✅ **Secrets** — `/opt/mako.env` root-owned, 640, group=mako
8. ✅ **iptables DOCKER-USER rules** — DNS (53), HTTP (80), HTTPS (443) allowed, all else dropped
9. ✅ **Docker DNS fix** — `/etc/docker/daemon.json` with Google/Cloudflare DNS
10. TODO: Systemd service for auto-start on boot (currently using `docker compose up -d` with `restart: unless-stopped`)

**Deliverable:** Mako runs 24/7 in a hardened Docker container on your Oracle VPS.

## VPS Deployment Details

- **User:** `mako` (new unprivileged user, manages container)
- **Home:** `/home/mako/`
- **App:** `/home/mako/mako/` (git repo)
- **Workspace volume:** `/home/mako/mako/workspace/` → mounted into container
- **Data volume:** `/home/mako/mako/data/` → SQLite DB, audit logs
- **Secrets:** `/opt/mako.env` (root-owned, 640, group=mako)
- **Service:** `/home/mako/.config/systemd/user/mako.service`
- **Port:** None exposed (Telegram polling, no inbound connections)
- **Container security:**
  - Read-only root filesystem
  - Non-root user inside container
  - Dropped capabilities
  - Memory/CPU limits
  - no-new-privileges
  - Outbound HTTPS only via iptables DOCKER-USER

## What Makes Mako Different from OpenClaw

1. **Security-first, not security-patched** — OpenClaw had 512 vulnerabilities found in its Jan 2026 audit. Mako's SecurityGuard is the first module built and gates every tool call. Deny-by-default, workspace jailing, command allowlists, and full audit logging from line 1.
2. **Fully auditable** — ~2-5K lines of Python vs 430K lines of TypeScript. You can read every line.
3. **Provider-agnostic** — swap between Gemini/Claude with a config change
4. **No plugins/skills system** — tools are just Python functions with decorators. No community skill registry = no supply chain attack surface.
5. **MCP-native** — connects to the standard ecosystem instead of a proprietary skill registry
6. **Full audit trail** — every tool call logged with timestamp, args, result, and the LLM reasoning that triggered it. You can replay exactly what the agent did and why.

## Verification

After each phase:
- **Phase 1:** ✅ Run `uv run mako`, have a conversation, ask it to fetch a URL. Check `workspace/audit.log` to see every tool call logged. Try a blocked command and verify it's rejected.
- **Phase 2:** Restart Mako, verify it remembers previous conversations. Verify SOUL.md personality loads.
- **Phase 3:** Send a Telegram message to Mako's bot, get a response
- **Phase 4:** Wait for 8 AM (or trigger manually), receive morning briefing on Telegram
- **Phase 5:** Configure an MCP server, verify Mako discovers and uses its tools
- **Phase 6:** SSH into VPS, run `docker compose logs mako`, send Telegram message, verify container is running with `docker ps`. Test security: verify read-only filesystem, dropped capabilities, memory limits.
