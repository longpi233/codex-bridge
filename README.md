# Codex GPT Bridge (`codex-bridge`)

<p align="center">
  <img src="./assets/logo-full.png" alt="codex-bridge logo" width="220" />
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

**`codex-bridge`** is a lightweight, zero-dependency **MCP server** and **native plugin** (for **Antigravity**, **Claude Code / Claude Desktop**, and **DeepSeek Harness**) that lets your favorite AI coding agent delegate tasks and code reviews to your local **OpenAI Codex CLI** (`codex`).

---

## Table of Contents

- [Why Use codex-bridge](#why-use-codex-bridge)
- [Available Tools](#available-tools)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Running Tests](#running-tests)
- [License](#license)

---

## Why Use codex-bridge

- **Smart Quota and Reset-Time Routing**: Your main agent can query live 5-hour and 7-day Codex limits (`codex_quota_status`) before delegating, knowing when to go all-in with `gpt-6.2-astra` and when to conserve quota.
- **No Client Timeouts on Deep Audits**: Supports asynchronous background execution (`background: true`) for long analyses and large git diff reviews, collecting results cleanly via `codex_job_status`.
- **Multi-Turn Context Continuity**: Preserves Codex sessions across follow-up turns so you can review, fix, and re-verify without starting from scratch.
- **Multimodal and Config Profiles**: Attach local screenshots to prompts (`images`) or reuse your existing `~/.codex` config profiles (`profile`).
- **Zero Dependencies, Cross-Platform**: Built purely on the Python 3.10+ standard library and works out of the box on Windows, macOS, and Linux.

## Available Tools

| Tool | What It Does |
| :--- | :--- |
| `codex_quota_status` | Checks live 5-hour / 7-day Codex quota, reset times, and recommends a model and reasoning effort. |
| `codex_list_models` | Lists the GPT models available on your Codex account along with supported reasoning efforts. |
| `codex_exec` | Runs non-interactive prompts, audits, or bounded subtasks with configurable sandbox, images, profiles, session resume, and background execution. |
| `codex_review` | Runs read-only git code reviews on uncommitted changes, branch diffs, specific commits, or custom focus areas. |
| `codex_job_status` | Monitors and collects results from background jobs and lists active resumable sessions. |
| `codex_job_cancel` | Cleanly cancels queued or running background jobs and terminates their child processes. |

---

## Prerequisites

1. **OpenAI Codex CLI** installed and signed in:
   ```bash
   codex --version
   codex login status    # Should show: Logged in using ChatGPT
   ```
2. **Python 3.10+** installed:
   ```bash
   python --version
   ```

---

## Installation and Setup

Choose your client:

- [1. Antigravity](#1-antigravity)
- [2. Claude Code and Claude Desktop](#2-claude-code-and-claude-desktop)
- [3. DeepSeek Harness](#3-deepseek-harness)
- [4. Cursor, Windsurf, WorkBuddy and Other MCP Clients](#4-cursor-windsurf-workbuddy-and-other-mcp-clients)

---

### 1. Antigravity

Installs the MCP server, `codex-delegate` skill, always-on rule, and `codex_worker` subagent as one bundle (shared across the Antigravity CLI and App).

- **Install via Antigravity CLI (`agy`, Recommended)**:
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git
  agy plugin install ./codex-bridge
  ```
- **Or clone directly into Antigravity's plugins folder**:
  - **macOS / Linux**:
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows (PowerShell)**:
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
  - **Windows (`cmd`)**:
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```
- **Or register an existing clone** in `~/.gemini/config/plugins.json`:
  ```json
  { "entries": [{ "path": "/path/to/parent-folder", "include_only": ["codex-bridge"] }] }
  ```

---

### 2. Claude Code and Claude Desktop

The native plugin bundles all 6 MCP tools, the `codex-delegate` skill, and a native `codex-worker` subagent *(on Claude Desktop, plugin-local MCP servers and subagents apply to **Cowork** and **Claude Code**; if you use the standard Desktop **Chat** tab, use [Manual Setup](#manual-setup-custom-python-path-or-environment-variables) below)*.

#### Option A: Sync via GitHub Marketplace (Recommended — Easy Updates)

- **Claude Desktop (Cowork)**:
  1. Open **Customize** → **Plugins** → **Discover** → click **`+`** *(hovering over `+` shows **Add marketplace**)*.
  2. Enter `longpi233/codex-bridge` and click **Sync**.
  3. Install **`codex-bridge`** from the synced marketplace.
- **Claude Code**:
  ```text
  # Claude Code 2.1.275+
  /plugin install codex-bridge --marketplace longpi233/codex-bridge

  # Earlier versions with /plugin
  /plugin marketplace add longpi233/codex-bridge
  /plugin install codex-bridge@codex-bridge
  /reload-plugins
  ```
  You can also load a local clone directly with `claude --plugin-dir /path/to/codex-bridge`.

#### Option B: Upload Prebuilt `.plugin` Package (Claude Desktop Cowork)

1. Download **`codex-bridge.plugin`** from [GitHub Releases](https://github.com/longpi233/codex-bridge/releases/latest) *(or build it locally with `python scripts/pack_claude_plugin.py`)*.
2. Open **Customize** → **Plugins** → **Upload local plugin** and select `codex-bridge.plugin`.

#### Manual Setup (Desktop Chat Tab, Custom Python Path, or Env Vars)

- **Claude Desktop (Chat / Cowork)**: Open **Settings… → Developer → Edit Config** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), use the JSON template in [§4](#4-cursor-windsurf-workbuddy-and-other-mcp-clients) with your Python path (`python` on Windows or `python3` / full path on macOS/Linux), then fully quit and relaunch Claude Desktop.
- **Claude Code CLI**:
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
  # Use `python3` instead of `python` on macOS/Linux if `python` is unavailable
  claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
  ```
  *(Add `-s user` before `codex-bridge` to register globally.)*

---

### 3. DeepSeek Harness

DSH supports `codex-bridge` as a native Cordis plugin bundle, automatically mounting all 6 MCP tools and the bundled `codex-delegate` skill (no manual skill copying required).

- **Install via DSH CLI (Recommended)**:
  ```bash
  # Replace `desktop` with your profile name if different (e.g. `web` or `tui`)
  dsh plugin --profile desktop add github:longpi233/codex-bridge
  ```
  *(Or pass a local clone path: `dsh plugin --profile desktop add /path/to/codex-bridge`.)*
  Then enable **`codex-bridge`** in DSH's Plugins page (or add `"codex-bridge"` to `dsh.profile.bundles` in `~/.dsh/profiles/<profile>/package.json`). *(If you previously added a manual `cordis.patch.yml` entry below, remove it before enabling the plugin bundle.)*

- **Or configure manually via `cordis.patch.yml`**:
  Append the entry below to `~/.dsh/profiles/<profile>/cordis.patch.yml` and save (DSH hot-reloads without restarting):
  ```yaml
  - insert:
      - id: codex-bridge-mcp-manual
        name: '@deepseek-ai/dsh-mcp-client'
        config:
          serverName: codex-bridge
          transport: stdio
          command: 'C:\Python311\python.exe'    # absolute path to Python
          args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
          cwd: 'D:\tools\codex-bridge'
          toolCallTimeoutMs: 1800000
          failOnStartupError: true
  ```

---

### 4. Cursor, Windsurf, WorkBuddy and Other MCP Clients

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```
2. **Add `codex_bridge` to your client's MCP configuration** (`~/.cursor/mcp.json`, `%USERPROFILE%\.workbuddy\mcp.json`, Windsurf `mcp_config.json`, etc.):
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
   - Replace `"/path/to/python"` with your Python executable path (e.g. `C:/Python311/python.exe` on Windows or `/usr/local/bin/python3` on macOS/Linux).
   - **WorkBuddy**: After saving `mcp.json`, completely quit and restart WorkBuddy, then open **Connectors → Custom Connectors** and click **Trust** on `codex_bridge`.
3. **Install the Skill & Rule (Recommended)**:
   - **Skill**: Copy or symlink `skills/codex-delegate/` to your client's skill folder (`~/.agents/skills/codex-delegate`, `.cursor/skills/codex-delegate`, `~/.workbuddy/skills/codex-delegate`, or `.codebuddy/skills/codex-delegate`).
   - **Rule**: Copy [`rules/AGENTS.md`](./rules/AGENTS.md) into your project's `AGENTS.md` or client rules directory.

---

## Quick Start

Once installed, try asking your main agent:

- *"Check my Codex quota and reset time, and recommend which GPT model and reasoning effort we should use."*
- *"Ask Codex (`gpt-6.2-astra`) in read-only background mode to review my uncommitted changes for bugs and edge cases."*
- *"Send this UI screenshot to Codex via `codex_exec` and check layout alignment against `src/App.tsx`."*

---

## Environment Variables

All environment variables are optional:

| Variable | Description |
| :--- | :--- |
| `CODEX_BIN` | Explicit path to `codex` / `codex.exe` if not on `PATH`. |
| `CODEX_HOME` | Custom Codex auth/state directory (defaults to `~/.codex`). |
| `CODEX_DEFAULT_MODEL` | Fallback model id when `model` and `profile` are omitted. |
| `CODEX_BRIDGE_PYTHON` | Explicit Python path for the native DSH plugin bundle. |
| `CODEX_BRIDGE_LOG_FILE` | File path to enable optional JSONL diagnostic logging. |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | Set to `1` to include unmasked `account.email` in quota status (masked by default). |

---

## Troubleshooting

If tools do not show up in your client, verify that the server itself responds cleanly:

- **Windows (PowerShell)**:
  ```powershell
  $p = @'
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
  {"jsonrpc":"2.0","method":"notifications/initialized"}
  {"jsonrpc":"2.0","id":2,"method":"tools/list"}
  '@
  $p | python -u server/codex_mcp_server.py
  ```
- **macOS / Linux**:
  ```bash
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | python3 -u server/codex_mcp_server.py
  ```

- **Prints 2 JSON lines listing all 6 tools**: The server is working — check your client's config path, specify the full path to Python, and fully restart the client (in WorkBuddy, also click **Trust** under Custom Connectors).
- **Hangs with no output**: Make sure `-u` is included in `args` so Python does not buffer stdout.

---

## Running Tests

```bash
# Offline test suite (zero model quota)
python tests/test_codex_bridge.py

# Live smoke tests using your local Codex CLI
python tests/test_codex_bridge.py --live
```

---

## License

Licensed under the [MIT License](./LICENSE).
