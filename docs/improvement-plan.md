# Mako Improvement Plan

Tracking 9 improvements from the comprehensive codebase review. Each item includes the problem, proposed fix, and files to modify.

---

## 1. Retry Logic for Transient Tool Failures [HIGH]

**Problem:** `web_fetch`, `shell`, and MCP tools fail immediately on transient errors (5xx, timeouts, network blips). The agent must manually decide to retry.

**Plan:**
- Add a shared `async def retry_with_backoff(fn, max_retries=3, base_delay=1.0)` utility in `src/mako/tools/retry.py`
- Exponential backoff: 1s, 2s, 4s (with jitter)
- Retry on: `httpx.TransportError`, 5xx status codes, `TimeoutError`
- Do NOT retry on: 4xx, `ValueError`, `SecurityError` (these are deterministic failures)
- Wrap `web_fetch` and MCP `call_tool` with the retry utility
- `shell` already has a 30s timeout — retry only on `TimeoutError`, not on non-zero exit codes

**Files:**
- `src/mako/tools/retry.py` (new — small utility, ~30 lines)
- `src/mako/tools/web_fetch.py` — wrap the HTTP call
- `src/mako/tools/mcp.py` — wrap `_send_request`

---

## 2. Cache System Prompt to Reduce Token Bloat [HIGH]

**Problem:** `ContextAssembler.build_system_prompt()` is called every turn, and the full system prompt (SOUL.md + IDENTITY.md + MEMORY.md) is included in every API call. Over 10 turns this wastes ~25k tokens.

**Plan:**
- Cache the assembled system prompt string in `ContextAssembler` (already partially done — files are cached, but `build_system_prompt()` rebuilds the string every call)
- Add a `_cached_system_prompt: str | None` field, invalidated by `reload()`
- In `build_system_prompt()`, return the cached value if set
- This is a small optimization since string concatenation is cheap, but the real win is on the provider side: Claude's API supports `system` as a top-level param (sent once), and Gemini supports `system_instruction`. Verify both providers use these correctly rather than prepending as a user message each turn.

**Files:**
- `src/mako/context.py` — cache the prompt string
- `src/mako/providers/claude.py` — verify `system` param usage
- `src/mako/providers/gemini.py` — verify `system_instruction` usage

---

## 3. Close DNS Rebinding Window in web_fetch [MEDIUM]

**Problem:** SSRF protection resolves DNS once, but there's a TOCTOU gap — an attacker could change DNS between validation and the actual HTTP request.

**Plan:**
- Create a custom `httpx.AsyncHTTPTransport` that hooks into connection setup and validates the resolved IP before connecting
- Alternatively (simpler): use `httpx`'s `extensions` or event hooks to inspect the connection's resolved address
- Simplest approach: resolve DNS ourselves via `socket.getaddrinfo`, then pass the resolved IP directly to httpx with a `Host` header override. This eliminates the rebinding window entirely.

**Implementation:**
```python
# Resolve once, connect to IP directly
ip = resolved_ip_from_validation
async with httpx.AsyncClient() as client:
    resp = await client.get(url, extensions={"sni_hostname": hostname})
```

Actually the simplest robust fix: after getting the response, check `resp.extensions["network_stream"]` or the connection's peer address. If it's private, reject. This is a post-connect check that closes the TOCTOU gap.

**Files:**
- `src/mako/tools/web_fetch.py` — add post-connect IP validation

---

## 4. Set SQLite Connection Timeout [MEDIUM]

**Problem:** `sqlite3.connect()` has no timeout, so lock contention causes indefinite blocking.

**Plan:**
- Add `timeout=30` to `sqlite3.connect()` call
- One-line fix

**Files:**
- `src/mako/memory/store.py` — add timeout parameter

---

## 5. Move Hard-Coded Limits to Config [MEDIUM]

**Problem:** Many limits are scattered across source files as module-level constants with no way to override them without code changes.

**Plan:**
- Add these to `Settings` in `config.py` with sensible defaults:
  - `max_pause_continuations` (default: 5) — claude.py
  - `max_retries` (default: 3) — claude.py
  - `retry_base_delay` (default: 60) — claude.py
  - `max_shell_output_length` (default: 8000) — shell.py
  - `max_web_fetch_content_length` (default: 3000) — web_fetch.py
  - `max_web_fetch_response_bytes` (default: 5MB) — web_fetch.py
- Pass `settings` to tool handlers that need these values (shell, web_fetch already receive workspace_path via closure — extend the pattern)
- Do NOT move `TELEGRAM_MAX_LENGTH` — that's a Telegram API limit, not configurable

**Files:**
- `src/mako/config.py` — add new settings fields
- `src/mako/tools/shell.py` — read from settings
- `src/mako/tools/web_fetch.py` — read from settings
- `src/mako/providers/claude.py` — read from settings
- `src/mako/main.py` — wire settings through

---

## 6. Track Visited URLs in web_fetch Redirects [LOW]

**Problem:** Redirect loop detection uses a counter but doesn't track visited URLs — a circular redirect (A → B → A) cycles within the 5-redirect limit.

**Plan:**
- Add a `visited: set[str]` that tracks each URL before following a redirect
- If a URL is already in the set, break and return what we have
- ~5 lines of code

**Files:**
- `src/mako/tools/web_fetch.py` — add visited set in redirect loop

---

## 7. Graceful Degradation for MCP Server Failures [LOW]

**Problem:** If an MCP server fails to start, the agent runs with partial functionality but nobody is informed. Users discover missing tools only when they try to use them.

**Plan:**
- `connect_mcp()` in `main.py` already catches exceptions per-server. Collect failed server names and return them.
- Include failed server names in the system prompt (e.g., append to `ContextAssembler` or pass to `Agent`)
- Log a clear warning at startup listing unavailable tools
- Optionally: add a `/status` Telegram command that lists connected MCP servers and their tool counts

**Files:**
- `src/mako/main.py` — collect and surface failed servers
- `src/mako/context.py` — optionally include in system prompt
- `src/mako/channels/telegram.py` — optionally add `/status` command

---

## 8. Audit Log Rotation [LOW]

**Problem:** `audit/audit.log` appends indefinitely with no rotation. Could grow to multi-GB over months.

**Plan:**
- Use Python's `logging.handlers.RotatingFileHandler` pattern but for the JSON audit log
- Implement simple size-based rotation: when file exceeds 10MB, rename to `audit.log.1` (keep 3 backups)
- Check file size before each write (cheap `os.path.getsize()` call)
- Alternative: just use `logrotate` on the VPS and document it. This is simpler and more Unix-idiomatic.

**Recommendation:** Go with `logrotate` config rather than in-code rotation. Add a `logrotate.d/mako` config file to the repo and document it in the README.

**Files:**
- `deploy/logrotate-mako` (new — logrotate config)
- Update deployment docs

---

## 9. Deduplicate Command Parsing [LOW]

**Problem:** `SecurityGuard.validate_command()` and `shell.py` both call `shlex.split()` independently. Redundant work with potentially different error messages.

**Plan:**
- Have `SecurityGuard.validate_command()` return the parsed args list instead of just validating
- Change signature: `def validate_command(self, command: str) -> list[str]` (returns parsed args)
- `shell.py` uses the returned args directly instead of re-parsing
- Need to update `pre_tool_call()` to store/return the parsed args, or have `shell` call `validate_command` directly

**Simplest approach:** `shell.py` calls `shlex.split()` first, then passes the already-parsed args to a new `SecurityGuard.validate_parsed_command(args)` method. This avoids changing the `pre_tool_call` interface.

**Files:**
- `src/mako/security.py` — add `validate_parsed_command()` or change return type
- `src/mako/tools/shell.py` — use parsed args from security guard

---

## Execution Order

Suggested order based on impact and dependency:

1. **Item 4** — SQLite timeout (1-line fix, ship immediately)
2. **Item 6** — Visited URL tracking (5-line fix, ship immediately)
3. **Item 1** — Retry utility (new file + 2 integrations, medium effort)
4. **Item 2** — Cache system prompt (verify provider behavior first)
5. **Item 9** — Deduplicate parsing (small refactor)
6. **Item 3** — DNS rebinding fix (needs careful testing)
7. **Item 5** — Configurable limits (many files, low risk)
8. **Item 7** — MCP graceful degradation (nice UX improvement)
9. **Item 8** — Audit log rotation (ops concern, logrotate config)
