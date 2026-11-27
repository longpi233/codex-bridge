# Codex GPT Bridge (`codex-bridge`)

English | [简体中文](./README_CN.md)

`Python 3.10+` · `Zero Dependencies` · `MCP stdio` · `Windows / macOS / Linux` · `MIT License`

> **Tired of GPT's defensive lecturing, robotic hedging, and refusal-flavored walls of text? Had enough of arguing with GPT just to get a straight answer?**
>
> Put an MCP bridge in between: let your sweet, empathetic **Gemini** (or whatever favorite AI agent you already love working with) do the talking with GPT under the hood. You keep all of GPT's heavy-duty reasoning and code-review horsepower — while your main agent handles the back-and-forth, filters the attitude, and translates every finding back to you in plain, pleasant human language. **Never stress over GPT not speaking human again.**

A cross-platform, zero-dependency **MCP stdio server** and **native plugin (Antigravity & Claude Code)** that connects AI coding agents (**Antigravity, Claude Code, Claude Desktop, DeepSeek Harness (DSH), Cursor, Windsurf, WorkBuddy, and any MCP stdio client**) to your local OpenAI Codex CLI (`codex`) on **Windows, macOS, and Linux**.

---

## Available MCP Tools

| Tool | Purpose | Key Capabilities |
| :--- | :--- | :--- |
| `codex_quota_status` | Live quota & routing | Queries `codex app-server` for 5h/7d rate-limit windows, exact reset times, surplus pacing ratio, and a 10-tier routing recommendation (falls back to session logs if offline). |
| `codex_list_models` | Model discovery | Lists available Codex GPT models (e.g., `gpt-6.2-sol`, `gpt-6.2-astra`) and supported reasoning efforts (`low` → `ultra`), automatically follows upstream pagination, and supports `include_hidden`. |
| `codex_exec` | Prompt execution | Runs non-interactive tasks with upfront `cwd` check, configurable `sandbox`, `-p` `profile`, `-i` `images` (multimodal), `ephemeral: false` + `session_id` resume, and `background: true` (with idempotent `request_id`). |
| `codex_review` | Git diff review | Read-only review of `--uncommitted`, `--base <branch>`, `--commit <sha>`, or custom `focus` instructions, with optional `profile`, idempotent `request_id`, and workspace-change detection (note: upstream `codex review` does not report token usage, returning `usageUnavailable: true`). |
| `codex_job_status` | Job & session tracking | Polls background jobs (`wait_seconds` up to `120s`, `idleSeconds`, `toolCallsCount`), waits on all active jobs when `job_id` is omitted, and lists `activeSessions`. |
| `codex_job_cancel` | Safe cancellation | Cancels queued or running jobs and kills the full child process tree (Windows Job Object on Windows; `start_new_session` + `os.killpg` on macOS/Linux). |

## Key Features

- **Quota- & Reset-Time-Aware Task Routing**: Knows when your 5-hour or 7-day quota is about to reset with unused balance (`use_it_or_lose_it`), abundant, moderate, or nearly exhausted—so your main agent picks the right model and reasoning effort automatically.
- **No More 3-Minute MCP Timeouts**: Pass `background: true` for deep `gpt-6.2-astra` (`high`/`xhigh`) audits or large git diffs, then collect results in one batch with `codex_job_status(wait_seconds=90–120, include_results=true)` (or `20–45` on 30–60s hosts).
- **Flexible Timeouts & Resumable Recovery**: Defaults to `900s`/`1800s` (or `timeout_seconds: 0` for agent-controlled runs). Background `codex_exec` jobs are resumable (`ephemeral: false`) by default, and timed-out/cancelled runs return full captured `agentMessages` and `activityLog` directly—no hunting through log files.
- **Multimodal & Config Profile Support**: Attach screenshots or diagrams to `codex_exec` via `images` (`-i`), or pass `profile` (`-p`) to reuse your `~/.codex` config profiles.
- **Multi-Turn Context Continuity**: Set `ephemeral: false` on the first turn to obtain a `sessionId`, resume it with full context and prompt caching, and inspect `activeSessions` anytime.
- **Built for Windows, macOS & Linux**: Zero external Python packages (standard library only), native `codex.exe` detection on Windows (x64 & ARM64), UTF-8 / locale (e.g. CP936/GBK) decoding fallback, and full process-tree cleanup across all OSes.

## Compatibility & Antigravity-Exclusive Features

| Component | Scope | Notes |
| :--- | :--- | :--- |
| `server/codex_mcp_server.py` | **Universal (All MCP clients, Win/macOS/Linux)** | Standard JSON-RPC 2.0 MCP stdio server exposing all 6 tools. |
| `skills/codex-delegate/` (`SKILL.md` + `references/playbook.md`) | **Cross-Agent** (with Antigravity notes) | Standard `SKILL.md` workflow compatible with Antigravity, Claude Code, Cursor, Pi, etc. Antigravity-specific notes are clearly marked. |
| `rules/AGENTS.md` | **Cross-Agent** (with Antigravity note) | Concise always-on delegation rule compatible with any agent supporting `AGENTS.md`. |
| `plugin.json` & `mcp_config.json` | **Antigravity-Exclusive** | Uses Antigravity's plugin manifest and `${PLUGIN_ROOT}` variable (mounted as `codex-bridge_codex-bridge`). |
| `.claude-plugin/` (`plugin.json`, `marketplace.json`) & `.mcp.json` | **Claude Code-Exclusive** | Native Claude Code plugin & marketplace manifests using `${CLAUDE_PLUGIN_ROOT}` to auto-load the MCP server + `codex-delegate` skill. |
| `agents/codex_worker.md` | **Antigravity-Exclusive** | Uses Antigravity subagent frontmatter (`subagent: true`, `call_mcp_tool`, `view_file`, etc.). |
| `RefreshMcpServers` reload endpoint (in `AGENTS.md`) | **Antigravity-Exclusive** | Hot-reloads only this MCP server inside a running Antigravity IDE instance. |

---

## Prerequisites

1. **OpenAI Codex CLI** installed and authenticated:
   ```bash
   codex --version       # Expected: codex-cli <version> (e.g., 0.172.0)
   codex login status    # Expected: Logged in using ChatGPT
   ```
2. **Python 3.10+** available on `PATH` (standard library only — no `pip install` needed):
   ```bash
   python --version      # Expected: Python 3.10+ (e.g., 3.11.5)
   ```

---

## Installation & Setup

Choose the setup guide for your AI client below:

### 1. Antigravity (All-in-One Plugin)

Antigravity loads the **MCP server, Skill (`codex-delegate`), Rule (`rules/AGENTS.md`), and Subagent (`codex_worker`)** automatically as a single bundle.

- **Option A — Clone directly into Antigravity's plugins directory** (simplest):
  - **macOS / Linux**:
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows (PowerShell)**:
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
    *(Windows PowerShell 5.1 passes `~` literally to native binaries like `git.exe`, creating a `~` folder in the current directory; always use `$env:USERPROFILE` instead.)*
  - **Windows (`cmd`)**:
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```

- **Option B — Clone to a custom directory and register it** (recommended if you keep repos elsewhere):
  1. Clone the repository to your preferred location:
     ```bash
     git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
     ```
  2. Register it in `~/.gemini/config/plugins.json`:
     ```json
     {
       "entries": [
         {
           "path": "/path/to/parent-folder-containing-codex-bridge",
           "include_only": ["codex-bridge"]
         }
       ]
     }
     ```
     Or create a symlink / directory junction into `~/.gemini/config/plugins/codex-bridge`:
     - **macOS / Linux**:
       ```bash
       ln -s /path/to/codex-bridge ~/.gemini/config/plugins/codex-bridge
       ```
     - **Windows (cmd)**:
       ```cmd
       mklink /J "%USERPROFILE%\.gemini\config\plugins\codex-bridge" "C:\path\to\codex-bridge"
       ```

`mcp_config.json` uses `${PLUGIN_ROOT}/server/codex_mcp_server.py`, so no path edits are needed inside Antigravity.

---

### 2. Claude Code (Native Plugin — Recommended, or Manual CLI)

`codex-bridge` ships with standard Claude Code plugin manifests (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`) validated by `claude plugin validate`.

- **Option A — Install as a Claude Code Plugin (Recommended)**:
  - **One-step install (Claude Code 2.1.275+)**:
    ```text
    /plugin install codex-bridge --marketplace longpi233/codex-bridge
    ```
  - **Or two-step install (all Claude Code versions with `/plugin`)**:
    ```text
    /plugin marketplace add longpi233/codex-bridge
    /plugin install codex-bridge@codex-bridge
    /reload-plugins
    ```
  - **Local development / cloned repo**:
    ```bash
    claude --plugin-dir /path/to/codex-bridge
    ```
  *(Both marketplace install and `--plugin-dir` auto-activate the `codex-bridge` MCP server and `codex-delegate` skill. They also register `agents/codex_worker.md`, which uses Antigravity-only frontmatter tools (`call_mcp_tool`, `view_file`), so in Claude Code invoke the `codex-bridge` tools from the main agent using `codex-delegate` rather than invoking `codex_worker`.)*

- **Option B — Manual CLI Registration (`claude mcp add-json` + Skill)**:
  1. **Clone the repository**:
     ```bash
     git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
     ```
  2. **Register and verify the MCP server**:
     ```bash
     claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
     claude mcp get codex-bridge
     ```
     *(On Windows, use forward slashes like `C:/path/to/codex-bridge/server/codex_mcp_server.py`, and expect `Status: √ Connected` from `claude mcp get`. Add `-s user` before `codex-bridge` to register globally. Note: on some Claude Code builds such as `2.1.332`, `claude mcp add ... -- python -u ...` fails with `error: unknown option '-u'`—use `add-json` instead and never drop `-u`, or Python will block-buffer pipe stdout and appear to hang.)*
  3. **Install the `codex-delegate` Skill & Rule** (optional):
     - **Global**: link/copy `skills/codex-delegate` to `~/.claude/skills/codex-delegate` (macOS/Linux: `ln -s /path/to/codex-bridge/skills/codex-delegate ~/.claude/skills/codex-delegate`; Windows `cmd`: `mklink /J "%USERPROFILE%\.claude\skills\codex-delegate" "C:\path\to\codex-bridge\skills\codex-delegate"`).
     - **Project-local**: copy into `<your-project>/.claude/skills/codex-delegate`.
     - **Rule**: append [`rules/AGENTS.md`](./rules/AGENTS.md) into `~/.claude/CLAUDE.md` (or project `CLAUDE.md`).

---

### 3. Claude Desktop (macOS / Windows Desktop App)

Claude Desktop supports the same `.claude-plugin/plugin.json` + `.mcp.json` (`stdio` + `${CLAUDE_PLUGIN_ROOT}`) + `skills/` format via local `.plugin`/`.zip` uploads, as well as manual `claude_desktop_config.json` setup.

#### Option A: Upload `.plugin` Package (Recommended — MCP + Skill together)

1. **Clone the repository and build the clean plugin package**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git
   cd codex-bridge
   python scripts/pack_claude_plugin.py
   ```
   This generates `dist/codex-bridge.plugin` containing only `.claude-plugin/plugin.json`, `.mcp.json`, `server/codex_mcp_server.py`, `skills/codex-delegate/`, and `LICENSE` (excluding Antigravity-only files such as `agents/codex_worker.md`).

2. **Upload in Claude Desktop**:
   - Open **Settings…** → **Customize** → **Plugins** → **Upload local plugin**.
   - Drag or select `dist/codex-bridge.plugin`.
   - This registers all 6 MCP tools via local `stdio` (`${CLAUDE_PLUGIN_ROOT}`) and installs the `codex-delegate` skill in one step.
   - **If the 6 tools do not appear**: `.mcp.json` launches bare `"command": "python"`. If the Desktop GUI process does not inherit your shell `PATH` (or hits the Windows Microsoft Store `python` stub), switch to **Option B** below and specify an absolute `python.exe` / `python3` path.

#### Option B: Manual `claude_desktop_config.json` (Custom `python` path / `env` or MCP only)

Use this option if Claude Desktop's GUI process does not inherit `python` in `PATH`, or if you want to pass custom `env` variables (`CODEX_BIN`, `CODEX_HOME`, `CODEX_DEFAULT_MODEL`) or install only the MCP server without the plugin bundle.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **Open Claude Desktop's MCP config file**:
   - In Claude Desktop: open **Settings…** → **Developer** → **Edit Config** (or edit the file directly):
     - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
     - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

3. **Add `codex-bridge` under `mcpServers`** (use absolute paths for both `python` and `codex_mcp_server.py` since GUI apps often do not inherit your shell `PATH`):
   - **Windows**:
     ```json
     {
       "mcpServers": {
         "codex-bridge": {
           "command": "C:/path/to/python.exe",
           "args": [
             "-u",
             "C:/path/to/codex-bridge/server/codex_mcp_server.py"
           ]
         }
       }
     }
     ```
   - **macOS**:
     ```json
     {
       "mcpServers": {
         "codex-bridge": {
           "command": "/usr/local/bin/python3",
           "args": [
             "-u",
             "/path/to/codex-bridge/server/codex_mcp_server.py"
           ]
         }
       }
     }
     ```

4. **Fully Quit and Restart Claude Desktop**:
   - Saving the JSON is not enough — **quit Claude Desktop completely** (from the system tray / menu bar) and relaunch it.
   - If the tools do not appear, check **Settings → Developer → Open Logs Folder** for startup diagnostics (e.g., verify `python` path via `where python` on Windows or `which python3` on macOS).

---

### 4. Cursor, Windsurf, WorkBuddy & Other MCP Clients (MCP Server + Skill & Rule)

> **Config File Ownership (do not copy the wrong template)**:
>
> | Client | Config Path | Path Variable | Default Server Key → Tool Prefix |
> | :--- | :--- | :--- | :--- |
> | **Antigravity** | `mcp_config.json` (built-in) | `${PLUGIN_ROOT}` | `codex-bridge_codex-bridge` (`call_mcp_tool`) |
> | **Claude Code / Desktop Plugin** | `.mcp.json` (built-in) | `${CLAUDE_PLUGIN_ROOT}` | `codex-bridge` → `mcp__codex-bridge__<tool>` |
> | **WorkBuddy / Cursor / Windsurf** | `~/.workbuddy/mcp.json`, `.workbuddy/mcp.json`, `~/.cursor/mcp.json` | Absolute paths only | `codex_bridge` → `mcp__codex_bridge__<tool>` |
> | **DSH (Section 5)** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | Absolute paths (YAML) | `codex-bridge` → `mcp__codex-bridge__<tool>` |
>
> **Never** copy `mcp_config.json` (`${PLUGIN_ROOT}`) or `.mcp.json` (`${CLAUDE_PLUGIN_ROOT}`) into Cursor, WorkBuddy, or DSH. Check your host's actual tool list if unsure of the active prefix.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **Add `codex-bridge` to your client's MCP configuration** (e.g. `~/.cursor/mcp.json`, `.cursor/mcp.json`, Windows `%USERPROFILE%\.workbuddy\mcp.json` or project `<project>\.workbuddy\mcp.json`, or Windsurf's `mcp_config.json`; for **DSH**, see **Section 5** below):

   ```json
   {
     "mcpServers": {
       "codex_bridge": {
         "command": "/path/to/python",
         "args": [
           "-u",
           "/path/to/codex-bridge/server/codex_mcp_server.py"
         ]
       }
     }
   }
   ```
   - **Absolute Python path**: Replace `"/path/to/python"` with your real interpreter path (e.g. `C:/Python311/python.exe` on Windows using forward slashes, or `/usr/local/bin/python3` on macOS/Linux; bare `"python"` only works if the GUI inherits your terminal `PATH`).
   - **Hosts with short or unknown per-call timeouts**: Even a small sync `codex_review` can take ~45s+, so on hosts with short (30–60s) or unverified per-call ceilings (e.g. WorkBuddy, where `mcp.json` `timeout` governs connection startup rather than per-call execution), **always** use `background: true` for `codex_review` and `medium`+ tasks and keep `codex_job_status` `wait_seconds` at `20`–`45` (unless raised in host config, such as DSH's verified `toolCallTimeoutMs`). Note also that `jobId` is per-server-process, while `sessionId` (default for `background: true` jobs) is persisted to disk by Codex CLI and survives restarts.

3. **Activate in WorkBuddy (required before tools appear)**:
   - After writing `%USERPROFILE%\.workbuddy\mcp.json` (or `<project>\.workbuddy\mcp.json`), **completely quit and restart WorkBuddy**.
   - Open **Connectors / Custom Connectors**, click **Trust** on `codex_bridge`, and confirm the status indicator turns green. Only after trusting will all 6 `mcp__codex_bridge__*` tools be injected. (Python edits also require a full restart/reconnect.)

4. **Install the `codex-delegate` Skill & Rule** (recommended):
   - **Skill**: Copy or symlink `skills/codex-delegate/` into your agent's skill directory:
     - Standard cross-agent path (Cursor / Pi / Codex / etc.): `.agents/skills/codex-delegate` or `~/.agents/skills/codex-delegate`
     - Cursor / WorkBuddy paths: `.cursor/skills/codex-delegate`, `~/.workbuddy/skills/codex-delegate`, or `.codebuddy/skills/codex-delegate`
     - DeepSeek Harness (DSH): `~/.dsh/skills/codex-delegate` (note: `.agents/skills/` does not apply to DSH)
   - **Rule**: Copy [`rules/AGENTS.md`](./rules/AGENTS.md) into your project's `AGENTS.md` (or your client's rules directory, e.g. `.cursor/rules/` or `.codebuddy/rules/`).

---

### 5. DeepSeek Harness (DSH)

DSH does **not** use a JSON `mcp.json`. MCP servers are registered in a Cordis patch layer, and skills live in `~/.dsh/skills/`.

1. **Append a server entry to `~/.dsh/profiles/<profile>/cordis.patch.yml`** (a top-level YAML list; check first with `grep serverName cordis.patch.yml` so you do not insert a duplicate `codex-bridge` server if a bundle or previous entry exists):
   ```yaml
   - insert:
       - id: codex-bridge-mcp
         name: '@deepseek-ai/dsh-mcp-client'
         config:
           serverName: codex-bridge
           transport: stdio
           command: 'C:\Python311\python.exe'      # absolute path: DSH does not inherit your shell PATH
           args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
           cwd: 'D:\tools\codex-bridge'
           toolCallTimeoutMs: 1800000              # REQUIRED — see step 3
           failOnStartupError: true
   ```
   *(If DSH's `install_bundle` hits `ERR_PNPM_UNEXPECTED_STORE` due to pnpm v10/v11 store mismatch in an existing profile, using `cordis.patch.yml` directly bypasses pnpm completely.)*

2. **Save and hot-reload**: DSH's Loader hot-reloads the patch **without restarting DSH**. All 6 tools appear as `mcp__codex-bridge__<tool>` (hyphen form, matching Claude Code).

3. **Set `toolCallTimeoutMs: 1800000` (required for long polls)**: DSH defaults to `60000` ms, which cuts a `wait_seconds=90` `codex_job_status` poll at 60s with `Error: Request timed out`. With `toolCallTimeoutMs: 1800000`, heavy polls (e.g. `88.6s`) return normally; otherwise keep `wait_seconds` between `20` and `45`.

4. **Timeout recovery**: A host-side RPC timeout does **not** kill the MCP stdio server or the background Codex job — simply call `codex_job_status` again to collect the finished result.

5. **Install the Skill**: Copy `skills/codex-delegate/` to `~/.dsh/skills/codex-delegate` (Windows: `C:\Users\<user>\.dsh\skills\codex-delegate`).

---

## Quick Start Prompts

Once connected, try asking your main agent:

- *"Check my Codex quota and reset time, and tell me which GPT model and reasoning effort we should use right now."*
- *"Ask Codex (`gpt-6.2-astra`) in read-only background mode to review our uncommitted changes for race conditions and edge cases."*
- *"Send this UI screenshot to Codex via `codex_exec` (`images`) and ask it to check layout alignment against `src/App.tsx`."*

## Optional Environment Variables

| Variable | Description |
| :--- | :--- |
| `CODEX_BIN` | Explicit path to the `codex` / `codex.exe` binary if not auto-detected from `PATH`. |
| `CODEX_HOME` | Custom Codex state/auth directory (defaults to `~/.codex`). |
| `CODEX_DEFAULT_MODEL` | Optional fallback model id when `model` and `profile` are omitted (if unset, Codex CLI uses its own configured default). |
| `CODEX_BRIDGE_LOG_FILE` | Optional file path for structured JSONL request/job diagnostic logs (disabled by default; never writes to `stderr`). |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | Set to `1` to return unmasked `account.email` in `codex_quota_status` (masked by default). |

## Running Tests

Run the offline unit, concurrency, cancellation, and CLI-flag tests (consumes zero model quota):

```bash
python tests/test_codex_bridge.py
```

Include live Codex CLI / `app-server` smoke tests (measured baseline ~23k–110k input tokens on `gpt-6-luna` `low` depending on whether tool calls trigger; skip when quota is tight):

```bash
python tests/test_codex_bridge.py --live
```

## Troubleshooting & Server Self-Check

If tools do not appear in your client, verify the MCP server directly over stdio first:

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

How to read the output & next steps:

| Symptom | Diagnosis & Fix |
| :--- | :--- |
| **Stdio self-check prints 2 JSON lines** (`initialize` + `tools/list` with 6 tools), **yet tools are missing in client** | Server is healthy; issue is client activation. **WorkBuddy**: completely quit, restart, and click **Trust** in Custom Connectors. **Claude Desktop**: completely quit from tray/menu bar and relaunch. |
| **Client shows red status light / startup failure** | Check JSON syntax, absolute `python` path (avoid bare `"python"`), `CODEX_BIN` / `CODEX_HOME`, or temporarily set `CODEX_BRIDGE_LOG_FILE` to inspect incoming requests. |
| **Self-check returns no output or traceback** | Verify Python `3.10+` and dependencies in `PATH`, and check client startup logs. |
| **Self-check hangs without printing** | Ensure `-u` is passed to Python so pipe `stdout` is unbuffered. |

## Directory Structure

```text
codex-bridge/
├── .claude-plugin/
│   ├── plugin.json                    # Claude Code plugin manifest
│   └── marketplace.json               # Claude Code marketplace manifest
├── .mcp.json                          # Claude Code plugin MCP config (${CLAUDE_PLUGIN_ROOT})
├── plugin.json                        # Antigravity plugin manifest
├── mcp_config.json                    # Antigravity MCP config (${PLUGIN_ROOT})
├── AGENTS.md                          # Repo guide for AI agents modifying this codebase
├── README.md                          # Documentation (English)
├── README_CN.md                       # Documentation (简体中文)
├── LICENSE                            # MIT License
├── .gitignore
├── scripts/
│   └── pack_claude_plugin.py          # Builds clean dist/codex-bridge.plugin archive
├── server/
│   └── codex_mcp_server.py            # Cross-platform MCP stdio server (zero dependencies)
├── skills/
│   └── codex-delegate/
│       ├── SKILL.md                   # Progressive-disclosure delegation skill
│       └── references/
│           └── playbook.md            # Copy-ready MCP tool argument recipes
├── agents/
│   └── codex_worker.md                # Antigravity subagent definition
├── rules/
│   └── AGENTS.md                      # Concise delegation rule
└── tests/
    └── test_codex_bridge.py           # Offline + optional --live test suite
```

## License

Licensed under the [MIT License](./LICENSE).
