# Codex GPT Bridge (`codex-bridge`)

<p align="center">
  <img src="./assets/logo.png" alt="codex-bridge logo" width="220" />
</p>

<p align="center">
  <strong>English</strong> | <a href="./README_CN.md">简体中文</a>
</p>

<p align="center">
  <code>Python 3.10+</code> · <code>Zero Dependencies</code> · <code>MCP stdio</code> · <code>Windows / macOS / Linux</code> · <code>MIT License</code>
</p>

> **Tired of GPT's defensive lecturing, robotic hedging, and refusal-flavored walls of text? Had enough of arguing with GPT just to get a straight answer?**
>
> Put an MCP bridge in between: let **Gemini**, **Claude**, or whichever main coding agent you already love handle the conversation under the hood. You keep all of GPT's heavy-duty reasoning and code-review horsepower — while your main agent manages the back-and-forth, filters the attitude, and translates every finding back to you in plain human language.

**`codex-bridge`** is a cross-platform, zero-dependency **MCP stdio server** and **native plugin** (for **Claude Code / Claude Desktop**, **Antigravity**, and **DeepSeek Harness / DSH**) that connects AI coding agents to your local **OpenAI Codex CLI** (`codex`) on Windows, macOS, and Linux.

---

## Table of Contents

- [Key Features](#key-features)
- [Available Tools](#available-tools)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [License](#license)

---

## Key Features

- **Quota- and Reset-Aware Routing**: Queries live 5-hour and 7-day rate-limit windows (`codex app-server`) to detect `use_it_or_lose_it`, `abundant`, `moderate`, or `conserve` states so your main agent chooses the right model and reasoning effort automatically.
- **No MCP Client Timeouts**: Offloads heavy audits or large diffs via `background: true` and batch-collects active jobs in one call (`codex_job_status`), with host-aware `wait_seconds` guidance (`90–120s` for 180s+ hosts; `20–45s` for 30–60s hosts).
- **Resumable Sessions and Clean Recovery**: Background jobs persist sessions by default (`ephemeral: false`) so interrupted or paused runs can resume with full context and prompt caching, while returning captured `agentMessages` and `activityLog` directly.
- **Multimodal and Config Profiles**: Pass local screenshots to `codex_exec` via `images` (`-i`) or reuse your `~/.codex` config profiles via `profile` (`-p`).
- **Zero-Dependency Cross-OS Support**: Uses only the Python 3.10+ standard library, detects native `codex.exe` on Windows (x64/ARM64) with UTF-8 / locale decoding fallback, and cleans up full process trees across Windows, macOS, and Linux.

## Available Tools

| Tool | Purpose | Key Capabilities |
| :--- | :--- | :--- |
| `codex_quota_status` | Live quota & routing | Queries live 5h/7d windows, reset timestamps, surplus pacing ratio, and a 10-tier recommendation (masks `account.email` by default; falls back to session logs offline). |
| `codex_list_models` | Model discovery | Lists available Codex GPT models (e.g. `gpt-6.2-sol`, `gpt-6.2-astra`) and supported reasoning efforts (`low` → `ultra`), following upstream pagination automatically. |
| `codex_exec` | Prompt execution | Non-interactive execution with `cwd` check, `sandbox`, `profile` (`-p`), `images` (`-i`), `session_id` multi-turn resume, `background: true`, and idempotent `request_id`. Sets `usageUnavailable: true` when upstream omits usage. |
| `codex_review` | Git diff review | Read-only review of `--uncommitted`, `--base <branch>`, `--commit <sha>`, or custom `focus` instructions with `profile` and workspace-change checks (sets `usageUnavailable: true` since upstream `codex review` omits token counts). |
| `codex_job_status` | Job & session tracking | Polls background jobs (`wait_seconds`, `idleSeconds`, `toolCallsCount`), waits on all active jobs when `job_id` is omitted, and lists tracked `activeSessions`. |
| `codex_job_cancel` | Safe cancellation | Cancels queued or running jobs and terminates the full child process tree (Windows Job Object on Windows; process-group `SIGTERM`/`SIGKILL` on POSIX). |

---

## Prerequisites

1. **OpenAI Codex CLI** installed and signed in:
   ```bash
   codex --version       # Expected: codex-cli <version>
   codex login status    # Expected: Logged in using ChatGPT
   ```
2. **Python 3.10+** available on `PATH`:
   ```bash
   python --version      # Expected: Python 3.10+
   ```

---

## Installation and Setup

Jump to your client (ordered from dedicated native plugins to generic MCP configuration):

- [1. Claude Code and Claude Desktop](#1-claude-code-and-claude-desktop) — Native plugin, GitHub Marketplace, Release `.plugin`, and CLI
- [2. Antigravity](#2-antigravity) — All-in-one plugin (MCP + Skill + Rule + `codex_worker` subagent)
- [3. DeepSeek Harness (DSH)](#3-deepseek-harness) — Native Cordis plugin bundle or `cordis.patch.yml`
- [4. Generic MCP Clients](#4-generic-mcp-clients) — Cursor, Windsurf, WorkBuddy, and manual JSON config

---

### 1. Claude Code and Claude Desktop

`codex-bridge` ships standard Anthropic plugin manifests (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`) validated with `claude plugin validate`.

#### Claude Desktop

1. **Recommended — Upload `.plugin` from [GitHub Releases](https://github.com/longpi233/codex-bridge/releases/latest)**:
   - Download **`codex-bridge.plugin`** from the latest Release Assets *(excludes Antigravity-only files and works offline; or build locally via `python scripts/pack_claude_plugin.py`)*.
   - Open **Settings…** → **Customize** → **Plugins** → **Upload local plugin** and select `codex-bridge.plugin`.
2. **Or Sync Directly from GitHub Marketplace**:
   - Open **Customize** → **Plugins** → **+ Add** → **Add marketplace**.
   - Enter `longpi233/codex-bridge` and click **Sync**, then install `codex-bridge`.
3. **If the 6 tools do not appear** *(Claude Desktop's GUI does not inherit `python` on `PATH` or hits the Windows Store stub)*:
   - Open **Settings… → Developer → Edit Config** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), paste the canonical JSON with your **absolute Python path** from [§4 Generic MCP Clients](#4-generic-mcp-clients), then **completely quit and relaunch** Claude Desktop from the system tray / menu bar.

#### Claude Code

- **Native Plugin (Recommended)**:
  ```text
  # Claude Code 2.1.275+
  /plugin install codex-bridge --marketplace longpi233/codex-bridge

  # Or two-step (all versions with /plugin)
  /plugin marketplace add longpi233/codex-bridge
  /plugin install codex-bridge@codex-bridge
  /reload-plugins
  ```
  Or load a local clone directly: `claude --plugin-dir /path/to/codex-bridge`.
- **Manual CLI Registration** *(use `add-json`; on some builds like `2.1.332`, `claude mcp add ... -- python -u ...` fails with `unknown option '-u'`)*:
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
  claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
  claude mcp get codex-bridge   # Expected: Status: √ Connected
  ```
  *(Pass `-s user` before `codex-bridge` for global registration. To also add the skill/rule manually, see [§4 Generic MCP Clients](#4-generic-mcp-clients) with `~/.claude/skills/codex-delegate` and `~/.claude/CLAUDE.md`.)*

> **Included components**: Both `.plugin` uploads and GitHub Marketplace / `--plugin-dir` installs load all 6 MCP tools, the `codex-delegate` skill, and the native `codex-worker` subagent (`claude/agents/codex-worker.md`, keeping Antigravity's `agents/codex_worker.md` isolated).

---

### 2. Antigravity

Antigravity automatically loads the **MCP server (`codex-bridge_codex-bridge`), `codex-delegate` Skill, `rules/AGENTS.md` Rule, and `codex_worker` subagent** together.

- **Clone directly into Antigravity's plugins folder**:
  - **macOS / Linux**:
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows (PowerShell)** *(use `$env:USERPROFILE` — PowerShell 5.1 passes `~` literally to `git.exe`)*:
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
  - **Windows (`cmd`)**:
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```
- **Or keep your clone elsewhere**: Clone anywhere and register its parent folder in `~/.gemini/config/plugins.json`:
  ```json
  { "entries": [{ "path": "/path/to/parent-folder", "include_only": ["codex-bridge"] }] }
  ```

---

### 3. DeepSeek Harness

DSH uses a Cordis plugin bundle (`package.json` + `cordis.patch.yml`) rather than a JSON `mcp.json`.

- **Option A — Native DSH Plugin Bundle (Recommended)**:
  1. Clone to a permanent directory (`git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge`).
  2. Install via DSH's Plugin Manager (`install_bundle` pointing at `/path/to/codex-bridge`). The bundle automatically locates Python (or `CODEX_BRIDGE_PYTHON`) and `codex_mcp_server.py`, sets `toolCallTimeoutMs: 1800000`, and disables itself if another `codex-bridge` row is already active.
  3. Install the skill to `~/.dsh/skills/codex-delegate` (`.agents/skills/` does not apply to DSH).

- **Option B — Manual Profile Patch** *(also bypasses `ERR_PNPM_UNEXPECTED_STORE` on older pnpm v10 profiles)*:
  Append to `~/.dsh/profiles/<profile>/cordis.patch.yml` (check first with `grep serverName cordis.patch.yml` or PowerShell `Select-String -Path cordis.patch.yml -Pattern serverName` to avoid duplicate `serverName: codex-bridge`), then save to hot-reload without restarting DSH:
  ```yaml
  - insert:
      - id: codex-bridge-mcp
        name: '@deepseek-ai/dsh-mcp-client'
        config:
          serverName: codex-bridge
          transport: stdio
          command: 'C:\Python311\python.exe'    # absolute path required
          args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
          cwd: 'D:\tools\codex-bridge'
          toolCallTimeoutMs: 1800000            # required: DSH defaults to 60000ms
          failOnStartupError: true
  ```
  > DSH's default `60000` ms timeout cuts long `codex_job_status` polls at 60s, though the background Codex job keeps running and can be collected on the next poll. Set `toolCallTimeoutMs: 1800000` or keep `wait_seconds` between `20` and `45`.

---

### 4. Generic MCP Clients

Use this standard configuration for **Cursor**, **Windsurf**, **WorkBuddy**, or manual **Claude Desktop** setups.

> **Do not** copy `mcp_config.json` (`${PLUGIN_ROOT}`) or `.mcp.json` (`${CLAUDE_PLUGIN_ROOT}`) into these clients — GUI apps cannot expand plugin root variables and often do not inherit your shell `PATH`.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```
2. **Add `codex_bridge` to your client's MCP config** (`~/.cursor/mcp.json`, `.cursor/mcp.json`, `%USERPROFILE%\.workbuddy\mcp.json` / `.workbuddy/mcp.json`, Windsurf `mcp_config.json`, or Claude Desktop's `claude_desktop_config.json`):
   ```json
   {
     "mcpServers": {
       "codex_bridge": {
         "command": "/path/to/python",
         "args": ["-u", "/path/to/codex-bridge/server/codex_mcp_server.py"]
       }
     }
   }
   ```
   - Replace `"/path/to/python"` with your real interpreter (e.g. `C:/Python311/python.exe` on Windows or `/usr/local/bin/python3` on macOS/Linux; bare `"python"` only works if the GUI inherits `PATH`).
   - **WorkBuddy activation**: After saving `mcp.json`, **completely quit and restart WorkBuddy**, open **Connectors → Custom Connectors**, click **Trust** on `codex_bridge`, and confirm the green indicator.
   - **Short / unknown call timeouts** *(e.g. WorkBuddy)*: Even a small sync `codex_review` can take ~45s+, so always pass `background: true` for `codex_review` and `medium`+ tasks, and keep `codex_job_status` `wait_seconds` at `20`–`45`.
3. **Install the `codex-delegate` Skill & Rule** (recommended):
   - **Skill**: Copy or link `skills/codex-delegate/` to `~/.agents/skills/codex-delegate`, `.cursor/skills/codex-delegate`, `~/.workbuddy/skills/codex-delegate`, `.codebuddy/skills/codex-delegate`, or `~/.dsh/skills/codex-delegate`.
   - **Rule**: Copy [`rules/AGENTS.md`](./rules/AGENTS.md) into your project's `AGENTS.md` or client rules folder.

| Client | Default Server Key | Exposed Tool Name |
| :--- | :--- | :--- |
| **Antigravity** | `codex-bridge_codex-bridge` | `call_mcp_tool` (`ServerName`) |
| **Claude Code / Desktop / DSH** | `codex-bridge` | `mcp__codex-bridge__<tool>` |
| **WorkBuddy / Cursor** | `codex_bridge` | `mcp__codex_bridge__<tool>` |

---

## Quick Start

Once connected, try asking your main agent:

- *"Check my Codex quota and reset time, and tell me which GPT model and reasoning effort we should use."*
- *"Ask Codex (`gpt-6.2-astra`) in read-only background mode to review our uncommitted changes for race conditions."*
- *"Send this screenshot to Codex via `codex_exec` (`images`) and check layout alignment against `src/App.tsx`."*

---

## Environment Variables

| Variable | Description |
| :--- | :--- |
| `CODEX_BIN` | Explicit path to `codex` / `codex.exe` if not on `PATH`. |
| `CODEX_HOME` | Custom Codex auth/state directory (defaults to `~/.codex`). |
| `CODEX_DEFAULT_MODEL` | Fallback model id when `model` and `profile` are omitted (unset = Codex CLI default). |
| `CODEX_BRIDGE_LOG_FILE` | Optional JSONL diagnostic log file path (off by default; never writes to `stderr`). |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | Set to `1` to return unmasked `account.email` in `codex_quota_status`. |
| `CODEX_BRIDGE_PYTHON` | Optional explicit Python path for the native DSH bundle (`cordis.patch.yml`). |

---

## Troubleshooting

Verify the MCP server directly over stdio before debugging client configs:

- **Windows (PowerShell)**:
  ```powershell
  $p = @'
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
  {"jsonrpc":"2.0","method":"notifications/initialized"}
  {"jsonrpc":"2.0","id":2,"method":"tools/list"}
  '@
  $p | python -u server/codex_mcp_server.py
  ```
- **macOS / Linux / bash**:
  ```bash
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | python -u server/codex_mcp_server.py
  ```

| Symptom | Diagnosis & Fix |
| :--- | :--- |
| **Stdio returns 2 JSON lines** (`initialize` + `tools/list`), **but tools are missing in client** | Server is healthy; activation/config issue. **WorkBuddy**: quit, restart, and **Trust** in Custom Connectors. **Claude Desktop**: quit from tray/menu bar and relaunch (or switch to [§4](#4-generic-mcp-clients) with an absolute Python path). |
| **Red status light / startup error** | Verify JSON/YAML syntax, absolute `python` path, `CODEX_BIN` / `CODEX_HOME`, or temporarily set `CODEX_BRIDGE_LOG_FILE`. |
| **Hangs without output** | Ensure `-u` is passed to Python so pipe `stdout` is unbuffered. |

---

## Running Tests

```bash
# Offline unit, concurrency, cancellation, and envelope tests (zero quota cost)
python tests/test_codex_bridge.py

# Live Codex CLI / app-server smoke tests (~23k–110k input tokens on gpt-6-luna low)
python tests/test_codex_bridge.py --live
```

---

## Project Structure

```text
codex-bridge/
├── assets/logo.png                    # Project & multi-client plugin icon
├── .claude-plugin/                    # Claude Code / Desktop plugin & marketplace manifests
├── .mcp.json                          # Claude plugin MCP config (${CLAUDE_PLUGIN_ROOT})
├── plugin.json                        # Antigravity plugin manifest
├── mcp_config.json                    # Antigravity MCP config (${PLUGIN_ROOT})
├── package.json                       # Native DSH bundle manifest
├── cordis.patch.yml                   # Native DSH Cordis patch definition
├── locale/                            # DSH localized metadata (en.json, zh.json)
├── server/codex_mcp_server.py         # Cross-platform MCP stdio server (zero dependencies)
├── skills/codex-delegate/             # Cross-agent delegation workflow & playbook
├── claude/agents/codex-worker.md      # Claude Code / Desktop subagent definition
├── agents/codex_worker.md             # Antigravity subagent definition
├── rules/AGENTS.md                    # Concise always-on delegation rule
├── scripts/pack_claude_plugin.py      # Builds dist/codex-bridge.plugin for Claude Desktop
└── tests/test_codex_bridge.py         # Offline + optional --live test suite
```

---

## License

Licensed under the [MIT License](./LICENSE).
