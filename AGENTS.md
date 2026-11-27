# Codex GPT Bridge — Agent & Contributor Guide

This file guides AI coding agents working inside the `codex-bridge` repository.
For runtime delegation instructions used in *other* workspaces, see `rules/AGENTS.md` (always-on summary) and `skills/codex-delegate/SKILL.md` (progressive-disclosure skill).

## Repository Layout

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json` — **Claude Code-exclusive** plugin/marketplace manifests using `${CLAUDE_PLUGIN_ROOT}` (`codex-bridge` version `0.2.0`).
- `plugin.json` — **Antigravity-exclusive** plugin manifest (`name: "codex-bridge"`, synced to version `0.2.0`). Do not add unsupported top-level fields.
- `mcp_config.json` — **Antigravity-exclusive** MCP server definition using `${PLUGIN_ROOT}/server/codex_mcp_server.py`.
- `server/codex_mcp_server.py` — Cross-platform (Windows/macOS/Linux), cross-agent, zero-dependency Python 3.10+ MCP stdio server exposing 6 tools:
  - `codex_quota_status`, `codex_list_models`, `codex_exec` (supports `-p` `profile`, `-i` `images`, `session_id`), `codex_review` (supports `-p` `profile`), `codex_job_status` (returns `activeSessions` when `job_id` omitted), `codex_job_cancel`.
- `skills/codex-delegate/SKILL.md` & `skills/codex-delegate/references/playbook.md` — Cross-agent delegation workflow & concrete call recipes (with Antigravity-only notes clearly marked).
- `agents/codex_worker.md` — **Antigravity-exclusive** subagent persona (`codex_worker`).
- `rules/AGENTS.md` — Cross-agent ultra-concise rule (injected into every turn while the plugin is enabled).
- `README.md` & `README_CN.md` — Open-source documentation (English & Simplified Chinese) covering Antigravity, Claude Code, Cursor, Windsurf, and generic MCP stdio clients.
- `tests/test_codex_bridge.py` — Cross-OS unit, mock concurrency/cancel, and optional `--live` Codex CLI tests.

## Critical Runtime Invariants (Do Not Break)

1. **Antigravity MCP server naming & timeout**:
   - Antigravity namespaces plugin MCP servers as `<plugin_name>_<server_name>`, so `ServerName` is always `"codex-bridge_codex-bridge"`.
   - Antigravity enforces a hard **3-minute (180s)** per-call timeout on synchronous `call_mcp_tool`. Long operations must use `background: true` + `codex_job_status(wait_seconds=...)` (`30`–`45` for `low`/`medium`, `90`–`120` for `high`/`xhigh`/`max`; lower to `20`–`45` on hosts with 30–60s call ceilings).
2. **MCP protocol & model defaults**:
   - `initialize` negotiates `protocolVersion` across `SUPPORTED_PROTOCOL_VERSIONS` (`2024-11-05` through `2025-11-25`) and responds with empty `resources/list` and `prompts/list`.
   - Never hardcode a specific model slug when `model` is omitted: honor `CODEX_DEFAULT_MODEL` if set, otherwise omit `-m` so Codex CLI uses the user's configured default.
3. **Codex CLI flag placement**:
   - Parent flags (`-C <dir>`, `-s <sandbox>`, `--color never`, `-p <profile>`) **must precede** subcommands (`review`, `resume`).
   - On `resume`, `-i <image>` flags go **after** `resume` and **before** `<session_id>`.
   - `codex exec review` forbids combining positional `[PROMPT]` (`focus`) with `--uncommitted`, `--base`, or `--commit`. When `focus` is combined with a diff scope, `tool_review` intentionally routes through read-only `codex exec`.
   - `codex app-server` handshake sends `"initialized"` (not `"notifications/initialized"`).
4. **Cross-OS encoding & process cleanup**:
   - Child process streams (`stdout`/`stderr`) are read as raw `bytes` and decoded via `_decode_bytes()` (strict `utf-8`, then `GetACP()`/`mbcs`/OS locale) so non-UTF-8 Windows errors (e.g. Chinese `os error 3`) do not corrupt into `\ufffd`.
   - `_resolve_codex_command()` resolves native `codex.exe` directly when installed via npm on Windows (x64 & ARM64) and preserves `CODEX_MANAGED_BY_NPM=1` / `CODEX_MANAGED_PACKAGE_ROOT` (including when `CODEX_BIN` points inside `@openai/codex`).
   - Subprocesses run inside `_WinJobObject` (`KILL_ON_JOB_CLOSE`) on Windows and in their own process group (`start_new_session=True` + `os.killpg`) on POSIX (macOS/Linux) so cancellation/timeout kills the full child process tree.
5. **Session & job safety**:
   - `main()` dispatches tool calls concurrently via `ThreadPoolExecutor` with `SEND_LOCK` and `notifications/cancelled` handling; never regress to single-threaded blocking inside `main()`.
   - Missing `rateLimits` windows must return `tier: "unknown"` (never `"abundant"`).
   - Resuming a `session_id` validates bound `cwd` and refuses silently downgrading a `workspace-write` session to `read-only`.

## Verification & Reload Commands

Run offline tests (zero quota cost) after any edit to `server/codex_mcp_server.py`:

```bash
python tests/test_codex_bridge.py
```

Run live smoke tests (consumes minimal `gpt-6-luna` `low` quota):

```bash
python tests/test_codex_bridge.py --live
```

Reload only this MCP server in a running Antigravity instance:

```bash
curl -sf -H "Content-Type: application/json" \
  -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" \
  -d '{"serverName": "codex-bridge_codex-bridge"}' \
  "http://${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}/exa.language_server_pb.LanguageServerService/RefreshMcpServers"
```
