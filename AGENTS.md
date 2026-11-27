# Codex GPT Bridge — Agent & Contributor Guide

This file guides AI coding agents working inside the `codex-bridge` repository.
For runtime delegation instructions used in *other* workspaces, see `rules/AGENTS.md` (always-on summary) and `skills/codex-delegate/SKILL.md` (progressive-disclosure skill).

## Repository Layout

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json` — **Claude Code-exclusive** plugin/marketplace manifests using `${CLAUDE_PLUGIN_ROOT}` (`codex-bridge` version `0.2.1`).
- `plugin.json` — **Antigravity-exclusive** plugin manifest (`name: "codex-bridge"`, synced to version `0.2.1`). Do not add unsupported top-level fields.
- `mcp_config.json` — **Antigravity-exclusive** MCP server definition using `${PLUGIN_ROOT}/server/codex_mcp_server.py`.
- `server/codex_mcp_server.py` — Cross-platform (Windows/macOS/Linux), cross-agent, zero-dependency Python 3.10+ MCP stdio server exposing 6 tools:
  - `codex_quota_status`, `codex_list_models`, `codex_exec` (supports `-p` `profile`, `-i` `images`, `session_id`), `codex_review` (supports `-p` `profile`), `codex_job_status` (returns `activeSessions` when `job_id` omitted), `codex_job_cancel`.
- `skills/codex-delegate/SKILL.md` & `skills/codex-delegate/references/playbook.md` — Cross-agent delegation workflow & concrete call recipes (with Antigravity-only notes clearly marked).
- `agents/codex_worker.md` — **Antigravity-exclusive** subagent persona (`codex_worker`).
- `rules/AGENTS.md` — Cross-agent ultra-concise rule (injected into every turn while the plugin is enabled).
- `scripts/pack_claude_plugin.py` — Builds gitignored `dist/codex-bridge.plugin` from a hardcoded file whitelist for Claude Desktop uploads.
- `README.md` & `README_CN.md` — Open-source documentation (English & Simplified Chinese) covering Antigravity, Claude Code, Claude Desktop, DSH, Cursor, Windsurf, WorkBuddy, and generic MCP stdio clients.
- `tests/test_codex_bridge.py` — Cross-OS unit, mock concurrency/cancel, and optional `--live` Codex CLI tests.

## Critical Runtime Invariants (Do Not Break)

1. **Antigravity MCP server naming & timeout**:
   - Antigravity namespaces plugin MCP servers as `<plugin_name>_<server_name>`, so `ServerName` is always `"codex-bridge_codex-bridge"`.
   - Antigravity enforces a hard **3-minute (180s)** per-call timeout on synchronous `call_mcp_tool`. Long operations must use `background: true` + `codex_job_status(wait_seconds=...)` (`30`–`45` for `low`/`medium`, `90`–`120` for `high`/`xhigh`/`max`; lower to `20`–`45` on hosts with 30–60s call ceilings).
2. **MCP protocol & model defaults**:
   - `initialize` negotiates `protocolVersion` across `SUPPORTED_PROTOCOL_VERSIONS` (`2024-11-05` through `2025-11-25`) and responds with empty `resources/list`, `resources/templates/list`, and `prompts/list`.
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
6. **Packaging & cross-host docs**:
   - Any new runtime file required by the MCP server or `codex-delegate` skill must be added to `scripts/pack_claude_plugin.py`'s whitelist, or packaged `.plugin` uploads will ship incomplete. `dist/` is gitignored — never reference a prebuilt artifact path as tracked.
   - Never assume a single host's call-timeout or tool-name prefix in server `note` strings, `_compute_recommendation()`, `SKILL.md`, or `playbook.md` (keep `_compute_recommendation()` free of `Antigravity`, `codex_worker`, or `invoke_subagent`). State the host prerequisite inline for any `wait_seconds` recommendation > `45`, keep skill tool names bare (`codex_exec`, etc.), and note that prefixes follow the host's configured server key.

## Verification & Reload Commands

Run offline tests (zero quota cost) after any edit to `server/codex_mcp_server.py`:

```bash
python tests/test_codex_bridge.py
```

Run live smoke tests (consumes `~20k–110k` input tokens on `gpt-6-luna` `low` depending on whether tool calls trigger; skip when quota is tight):

```bash
python tests/test_codex_bridge.py --live
```

Standalone MCP stdio self-check (verifies the server starts and lists all 6 tools independent of any client; expects 2 JSON-RPC response lines):

```powershell
# PowerShell
$p = @'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
'@
$p | python -u server/codex_mcp_server.py
```

```bash
# macOS / Linux / bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python -u server/codex_mcp_server.py
```

Reload this MCP server after edits:

| Client | How to reload |
| :--- | :--- |
| **Antigravity** | `curl -sf -H "Content-Type: application/json" -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" -d '{"serverName": "codex-bridge_codex-bridge"}' "http://${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}/exa.language_server_pb.LanguageServerService/RefreshMcpServers"` |
| **DSH** | Save `~/.dsh/profiles/<profile>/cordis.patch.yml` (Loader hot-reloads without restarting DSH; modifying the entry triggers unmount/remount). |
| **WorkBuddy** | After editing `~/.workbuddy/mcp.json` or `.py` files, completely quit and restart WorkBuddy, then trust the custom connector; Python modules do not hot-reload. |
| **Claude Code / Desktop / Cursor / Windsurf** | Restart or reconnect the MCP client after editing `.py` files (running MCP subprocesses do not hot-reload Python modules). |

> **Host timeout behavior**: A host-side tool-call timeout (e.g., DSH's default `60000` ms) cuts only the client RPC wait — it does **not** terminate the MCP stdio server or the background Codex job, which can still be collected via `codex_job_status`.
