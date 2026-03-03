# Mako - AI Agent Framework

## Project Overview
Mako is a minimal (~2-5K lines) Python AI agent framework built from scratch as a learning exercise.
It can run locally (CLI) or as a Telegram bot with scheduled jobs.

## Architecture
- **ReAct agent loop** in `src/mako/agent.py` — the core
- **Providers** abstract LLM APIs (Gemini, Claude) in `src/mako/providers/`
- **Tools** (web_fetch, shell, workspace files) in `src/mako/tools/`
- **Security** is the foundation — `src/mako/security.py` gates every tool call
- **Channels** (CLI, Telegram) in `src/mako/channels/`
- **Memory** (SQLite history, markdown files) in `src/mako/memory/`
- **Scheduler** for cron-like scheduled jobs in `src/mako/scheduler.py`

## Key Design Decisions
- Security-first: SecurityGuard validates every tool call before execution
- Deny-by-default: no tool runs unless explicitly allowed
- Workspace jail: file operations can't escape the workspace directory
- Command allowlist: shell tool only runs allowlisted commands
- Audit everything: every tool invocation logged outside the workspace

## Running
```bash
uv run mako          # CLI mode
uv run mako --telegram  # Telegram bot mode
uv run mako --debug     # Debug logging
```

## Testing
```bash
uv run pytest
```

## Tech Stack
- Python 3.12+, asyncio, httpx, pydantic, anthropic SDK
- No heavy frameworks — raw implementation for learning
