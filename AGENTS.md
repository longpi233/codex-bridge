# Codex GPT Bridge — Agent & Contributor Guide

This guide is for AI coding agents and contributors modifying `codex-bridge`.
Runtime delegation rules for *other* workspaces live in `rules/AGENTS.md` and `skills/codex-delegate/SKILL.md`.

## Repository Layout

- `assets/logo.png` & `assets/logo-96.png` — Transparent `512×512` PNG project logo (`< 256 KiB` for DSH compatibility) shared by READMEs and native plugin manifests, plus a `96×96` quantized PNG (`< 10 KiB`) inlined into MCP `serverInfo.icons` (`SERVER_INFO` `< 15.5k` chars) for Claude Desktop and MCP `2025-11-25` clients.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`, `claude/agents/codex-worker.md` — **Claude Code / Desktop** plugin manifests (`${CLAUDE_PLUGIN_ROOT}`, `codex-bridge` v`0.2.3`) and native Claude subagent (replaces auto-scanning Antigravity's `agents/`).
- `package.json`, `cordis.patch.yml`, `locale/en.json`, `locale/zh.json` — **DSH-exclusive** native Cordis plugin bundle (`name: "codex-bridge"`, synced to v`0.2.3`), resolving Python and `server/codex_mcp_server.py` dynamically via `!!js` with duplicate `serverName` auto-guard, and auto-mounting `skills/` via `@deepseek-ai/dsh-skill-filesystem` (`includeDefaultRoots: false`, `bundledSkillDir`).
- `plugin.json` & `mcp_config.json` — **Antigravity-exclusive** plugin manifest (`v0.2.3`) and MCP config (`${PLUGIN_ROOT}`). Do not add unsupported top-level fields.
- `server/codex_mcp_server.py` — Zero-dependency Python 3.10+ MCP stdio server exposing `codex_quota_status`, `codex_list_models`, `codex_exec`, `codex_review`, `codex_job_status`, and `codex_job_cancel`.
- `skills/codex-delegate/SKILL.md` & `skills/codex-delegate/references/playbook.md` — Cross-agent delegation workflow and argument recipes.
- `agents/codex_worker.md` — **Antigravity-exclusive** subagent persona (`codex_worker`).
- `rules/AGENTS.md` — Cross-agent concise delegation rule.
- `scripts/pack_claude_plugin.py` — Builds gitignored `dist/codex-bridge.plugin` from a hardcoded whitelist for Claude Desktop uploads.
- `README.md` & `README_CN.md` — Bilingual project documentation.
- `tests/test_codex_bridge.py` — Cross-OS offline unit/concurrency tests and optional `--live` Codex CLI smoke suite.

## Critical Runtime Invariants (Do Not Break)

1. **Antigravity naming & timeout**:
   - Antigravity mounts this plugin as `ServerName: "codex-bridge_codex-bridge"` and enforces a hard **180s** call timeout. Heavy runs must use `background: true` + `codex_job_status(wait_seconds=...)` (`30`–`45` for `low`/`medium`, `90`–`120` for `high`+; `20`–`45` on 30–60s hosts).
2. **MCP protocol & model defaults**:
   - `initialize` negotiates across `SUPPORTED_PROTOCOL_VERSIONS` (`2024-11-05`..`2025-11-25`) and responds with empty `resources/list`, `resources/templates/list`, and `prompts/list`.
   - `main()` validates JSON-RPC `id` / `requestId` (`_is_valid_jsonrpc_id`), catches `(json.JSONDecodeError, ValueError)` (Python 3.11+ huge ints), keeps `codex_job_cancel` on `control_executor`, and dispatches concurrently via `ThreadPoolExecutor` + `SEND_LOCK`.
   - When `model` is omitted, honor `CODEX_DEFAULT_MODEL` or omit `-m` so Codex CLI uses its configured default. Never hardcode a default model slug.
3. **Codex CLI flag placement**:
   - Parent flags (`-C <dir>`, `-s <sandbox>`, `--color never`, `-p <profile>`) **must precede** subcommands (`review`, `resume`). On `resume`, `-i <image>` goes **after** `resume` and **before** `<session_id>`.
   - `codex exec review` forbids combining positional `[PROMPT]` (`focus`) with `--uncommitted`/`--base`/`--commit`; `tool_review` routes `focus` + diff scope through read-only `codex exec`.
   - `codex app-server` handshake sends `"initialized"` (not `"notifications/initialized"`).
4. **Cross-OS encoding & process-tree cleanup**:
   - Subprocess streams are read as raw `bytes` and decoded via `_decode_bytes()` (strict `utf-8`, then Windows ACP/`mbcs`/locale).
   - `_resolve_codex_command()` prefers native `codex.exe` on Windows (x64/ARM64) and injects `CODEX_MANAGED_BY_NPM=1` / `CODEX_MANAGED_PACKAGE_ROOT`.
   - `_WinJobObject` uses typed Win32 ctypes bindings without `BREAKAWAY_OK`; POSIX `_terminate_process_tree()` signals `os.killpg` while skipping already-reaped processes (`returncode is not None`) to prevent PGID reuse.
5. **Session & job safety**:
   - Missing `rateLimits` windows must return `tier: "unknown"`; upstream absent/all-zero usage omits `usage` and sets `usageUnavailable: true`; `account.email` is masked unless `CODEX_BRIDGE_INCLUDE_EMAIL=1`.
   - `SESSION_LOCK_REFS` pins background session locks before worker thread creation so `_prune_sessions_unlocked()` cannot evict active/queued locks; resuming validates `cwd` and blocks downgrading `workspace-write` to `read-only`.
6. **Packaging, versions & cross-host docs**:
   - Keep version numbers, `assets/logo.png` (`512–2048 px` square PNG, **strictly `< 256 KiB`** for DSH), and `assets/logo-96.png` (`96×96` PNG, **strictly `< 10 KB`** so `SERVER_INFO` stays `< 16,000` chars) in sync across `server/codex_mcp_server.py`, `plugin.json`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `package.json`, and `scripts/pack_claude_plugin.py` (`dist/` is gitignored).
   - Keep `_compute_recommendation()`, server `note` strings, `SKILL.md`, and `playbook.md` free of single-host assumptions: keep skill tool names bare, inline host prerequisites for any `wait_seconds > 45`, and never reference `Antigravity` / `codex_worker` / `invoke_subagent` inside `_compute_recommendation()`.

## Verification & Reload Commands

```bash
# Offline tests (zero quota cost — run after any server/packer edit)
python tests/test_codex_bridge.py

# Validate Claude manifests & rebuild dist/codex-bridge.plugin
claude plugin validate --strict .
python scripts/pack_claude_plugin.py

# Live smoke tests (~23k–110k input tokens on gpt-6-luna low; skip when quota is tight)
python tests/test_codex_bridge.py --live
```

Standalone MCP stdio self-check (expects 2 JSON lines listing all 6 tools):

```powershell
# PowerShell
$p = @'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
'@
$p | python -u server/codex_mcp_server.py
```

| Client | How to Reload After Edits |
| :--- | :--- |
| **Antigravity** | `curl -sf -H "Content-Type: application/json" -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" -d '{"serverName": "codex-bridge_codex-bridge"}' "http://${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}/exa.language_server_pb.LanguageServerService/RefreshMcpServers"` |
| **DSH** | Save `~/.dsh/profiles/<profile>/cordis.patch.yml` (Loader hot-reloads without restarting DSH). |
| **WorkBuddy** | Fully quit and restart WorkBuddy after editing `mcp.json` or `.py` files, then trust the custom connector. |
| **Claude Code / Desktop / Cursor / Windsurf** | Restart or reconnect the MCP client after editing `.py` files. |

> Host-side tool-call timeouts (e.g. DSH's default `60000` ms) only cut the client RPC wait; background Codex jobs keep running and can still be collected via `codex_job_status`.
