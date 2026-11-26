# Codex GPT Bridge (`codex-bridge`)

English | [简体中文](./README_CN.md)

`Python 3.10+` · `Zero Dependencies` · `MCP stdio` · `Windows / macOS / Linux`

> **Tired of GPT's defensive lecturing, robotic hedging, and refusal-flavored walls of text? Had enough of arguing with GPT just to get a straight answer?**
>
> Put an MCP bridge in between: let your sweet, empathetic **Gemini** (or whatever favorite AI agent you already love working with) do the talking with GPT under the hood. You keep all of GPT's heavy-duty reasoning and code-review horsepower — while your main agent handles the back-and-forth, filters the attitude, and translates every finding back to you in plain, pleasant human language. **Never stress over GPT not speaking human again.**

A cross-platform, zero-dependency **MCP stdio server** and **Antigravity plugin** that connects AI coding agents (**Antigravity, Claude Code, Cursor, Windsurf, and any MCP stdio client**) to your local OpenAI Codex CLI (`codex`) on **Windows, macOS, and Linux**.

---

## Available MCP Tools

| Tool | Purpose | Key Capabilities |
| :--- | :--- | :--- |
| `codex_quota_status` | Live quota & routing | Queries `codex app-server` for 5h/7d rate-limit windows, exact reset times, surplus pacing ratio, and an 8-tier routing recommendation (falls back to session logs if offline). |
| `codex_list_models` | Model discovery | Lists available Codex GPT models (e.g., `gpt-6.2-sol`, `gpt-6.2-astra`) and supported reasoning efforts (`low` → `ultra`), with pagination and `include_hidden`. |
| `codex_exec` | Prompt execution | Runs non-interactive tasks with upfront `cwd` check, configurable `sandbox`, `-p` `profile`, `-i` `images` (multimodal), `ephemeral: false` + `session_id` resume, and `background: true`. |
| `codex_review` | Git diff review | Read-only review of `--uncommitted`, `--base <branch>`, `--commit <sha>`, or custom `focus` instructions, with optional `profile` and workspace-change detection. |
| `codex_job_status` | Job & session tracking | Polls background jobs (`wait_seconds`), deduplicates via `request_id`, and lists tracked resumable `activeSessions` when `job_id` is omitted. |
| `codex_job_cancel` | Safe cancellation | Cancels queued or running jobs and kills the full child process tree (Windows Job Object on Windows; `start_new_session` + `os.killpg` on macOS/Linux). |

## Key Features

- **Quota- & Reset-Time-Aware Task Routing**: Knows when your 5-hour or 7-day quota is about to reset with unused balance (`use_it_or_lose_it`), abundant, moderate, or nearly exhausted—so your main agent picks the right model and reasoning effort automatically.
- **No More 3-Minute MCP Timeouts**: Pass `background: true` for deep `gpt-6.2-astra` (`high`/`xhigh`) audits or large git diffs, then collect results safely with `codex_job_status(wait_seconds=25)`.
- **Multimodal & Config Profile Support**: Attach screenshots or diagrams to `codex_exec` via `images` (`-i`), or pass `profile` (`-p`) to reuse your `~/.codex` config profiles.
- **Multi-Turn Context Continuity**: Set `ephemeral: false` on the first turn to obtain a `sessionId`, resume it with full context and prompt caching, and inspect `activeSessions` anytime.
- **Built for Windows, macOS & Linux**: Zero external Python packages (standard library only), native `codex.exe` detection on Windows (x64 & ARM64), UTF-8 / locale (e.g. CP936/GBK) decoding fallback, and full process-tree cleanup across all OSes.

## Compatibility & Antigravity-Exclusive Features

| Component | Scope | Notes |
| :--- | :--- | :--- |
| `server/codex_mcp_server.py` | **Universal (All MCP clients, Win/macOS/Linux)** | Standard JSON-RPC 2.0 MCP stdio server exposing all 6 tools. |
| `skills/codex-delegate/` (`SKILL.md` + `references/playbook.md`) | **Cross-Agent** (with Antigravity notes) | Standard `SKILL.md` workflow compatible with Antigravity, Claude Code, Cursor, Pi, etc. Antigravity-specific notes are clearly marked. |
| `rules/AGENTS.md` | **Cross-Agent** (with Antigravity note) | Concise always-on delegation rule compatible with any agent supporting `AGENTS.md`. |
| `plugin.json` & `mcp_config.json` | **Antigravity-Exclusive** | Uses Antigravity's plugin manifest and `${PLUGIN_ROOT}` variable (mounted as `codex-bridge_codex-bridge`). Other clients must point to the absolute path of `server/codex_mcp_server.py`. |
| `agents/codex_worker.md` | **Antigravity-Exclusive** | Uses Antigravity subagent frontmatter (`subagent: true`, `call_mcp_tool`, `view_file`, etc.). |
| `RefreshMcpServers` reload endpoint (in `AGENTS.md`) | **Antigravity-Exclusive** | Hot-reloads only this MCP server inside a running Antigravity IDE instance. |

---

## Prerequisites

1. **OpenAI Codex CLI** installed and authenticated:
   ```bash
   codex --version
   codex login status
   ```
2. **Python 3.10+** available on `PATH` (standard library only — no `pip install` needed).

---

## Installation & Setup

Choose the setup guide for your AI client below:

### 1. Antigravity (All-in-One Plugin)

Antigravity loads the **MCP server, Skill (`codex-delegate`), Rule (`rules/AGENTS.md`), and Subagent (`codex_worker`)** automatically as a single bundle.

- **Option A — Clone directly into Antigravity's plugins directory** (simplest):
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
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

### 2. Claude Code (MCP Server + Skill & Rule)

> Do **not** copy `mcp_config.json` directly — `${PLUGIN_ROOT}` is Antigravity-only. Point Claude Code directly to `server/codex_mcp_server.py`.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **Register the MCP server**:
   ```bash
   claude mcp add codex-bridge -- python -u /path/to/codex-bridge/server/codex_mcp_server.py
   ```
   *(On Windows, use forward slashes like `C:/path/to/codex-bridge/server/codex_mcp_server.py`. Add `-s user` before `--` to register globally across all projects.)*

3. **Install the `codex-delegate` Skill** (optional, strongly recommended so Claude knows how to check quota, pick models, and use `background: true`):
   - **Global (all projects)**: copy or symlink `skills/codex-delegate` to `~/.claude/skills/codex-delegate`
     ```bash
     # macOS / Linux
     ln -s /path/to/codex-bridge/skills/codex-delegate ~/.claude/skills/codex-delegate

     # Windows (cmd junction)
     mklink /J "%USERPROFILE%\.claude\skills\codex-delegate" "C:\path\to\codex-bridge\skills\codex-delegate"
     ```
   - **Project-local**: copy or symlink into `<your-project>/.claude/skills/codex-delegate`.

4. **Add the Rule (optional)**:
   Append the short guidelines from [`rules/AGENTS.md`](./rules/AGENTS.md) into `~/.claude/CLAUDE.md` (or your project's `CLAUDE.md`).

---

### 3. Cursor, Windsurf & Other MCP Clients (MCP Server + Skill & Rule)

> Again, do **not** copy `mcp_config.json` with `${PLUGIN_ROOT}`. Use an absolute path to `server/codex_mcp_server.py`.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **Add `codex-bridge` to your client's MCP configuration** (e.g. `~/.cursor/mcp.json`, `.cursor/mcp.json`, or Windsurf's `mcp_config.json`):

   ```json
   {
     "mcpServers": {
       "codex-bridge": {
         "command": "python",
         "args": [
           "-u",
           "/path/to/codex-bridge/server/codex_mcp_server.py"
         ]
       }
     }
   }
   ```
   *(On Windows, use forward slashes like `"C:/path/to/codex-bridge/server/codex_mcp_server.py"`.)*

3. **Install the `codex-delegate` Skill & Rule** (recommended):
   - **Skill**: Copy or symlink `skills/codex-delegate/` into your agent's skill directory:
     - Standard cross-agent path (Cursor / Pi / Codex / etc.): `.agents/skills/codex-delegate` or `~/.agents/skills/codex-delegate`
     - Cursor-specific path: `.cursor/skills/codex-delegate` or `~/.cursor/skills/codex-delegate`
   - **Rule**: Copy [`rules/AGENTS.md`](./rules/AGENTS.md) into your project's `AGENTS.md` (or your client's rules directory, e.g. `.cursor/rules/`).

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

## Running Tests

Run the offline unit, concurrency, cancellation, and CLI-flag tests (consumes zero model quota):

```bash
python tests/test_codex_bridge.py
```

Include live Codex CLI / `app-server` smoke tests (consumes minimal `gpt-6-luna` `low` quota):

```bash
python tests/test_codex_bridge.py --live
```

## Directory Structure

```text
codex-bridge/
├── plugin.json                        # Antigravity plugin manifest
├── mcp_config.json                    # Antigravity MCP config (${PLUGIN_ROOT})
├── AGENTS.md                          # Repo guide for AI agents modifying this codebase
├── README.md                          # Documentation (English)
├── README_CN.md                       # Documentation (简体中文)
├── .gitignore
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
