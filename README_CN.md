# Codex GPT Bridge (`codex-bridge`)

[English](./README.md) | 简体中文

`Python 3.10+` · `零外部依赖` · `MCP stdio` · `Windows / macOS / Linux` · `MIT License`

> **受够了 GPT 动不动就防御性拉满、打官腔、摆架子？已经忍无可忍亲自下场和 GPT 扯皮了吗？**
>
> 换个思路，让 **MCP** 来替你受气：把那个可爱又善解人意的 **Gemini**（或者任何你顺手的 Claude / 主力 Agent）推到台前，由它去和后台的 GPT 沟通对线！你照样白嫖 GPT 强悍的深度推理与代码审计能力，而所有咬文嚼字、参数对齐、长篇大论的“非人类输出”，全交给贴心的主力 Agent 消化转译——**从此再也不用担心 GPT 不说人话了。**

这是一个跨平台、零第三方依赖的 **MCP stdio 服务端**与**原生双端插件（Antigravity & Claude Code）**，可在 **Windows、macOS 和 Linux** 上将各类 AI 编程助手（**Antigravity、Claude Code、Claude Desktop、DeepSeek Harness (DSH)、Cursor、Windsurf、WorkBuddy 及任意支持 MCP stdio 的客户端**）桥接到你本地的 OpenAI Codex CLI（`codex`）。

---

## 暴露的 MCP 工具

| 工具名 | 用途 | 核心能力 |
| :--- | :--- | :--- |
| `codex_quota_status` | 实时配额与路由 | 查询 `codex app-server` 获取 5 小时/7 天双窗口限额、精确重置时间、配额盈余比，并生成 10 档模型与推理强度建议（离线时自动降级读取本地会话日志）。 |
| `codex_list_models` | 模型发现 | 列出当前本地 Codex CLI 可用的 GPT 模型（如 `gpt-6.2-sol`、`gpt-6.2-astra`）及支持的推理强度（`low` → `ultra`），自动翻页拉取全部上游模型，支持 `include_hidden`。 |
| `codex_exec` | 非交互执行 | 预先校验 `cwd`，支持自定义 `sandbox`、`-p` `profile`、`-i` `images`（多模态传图）、`ephemeral: false` + `session_id` 多轮续接，以及 `background: true` 后台运行（支持 `request_id` 幂等去重）。 |
| `codex_review` | Git 差异审查 | 以严格 `read-only` 模式审查 `--uncommitted`、`--base <branch>`、`--commit <sha>` 或自定义 `focus` 审查重点，支持 `profile`、`request_id` 幂等去重及审查期间工作区变更检测（注：上游 `codex review` 不回传 token 用量，会返回 `usageUnavailable: true`）。 |
| `codex_job_status` | 任务与会话查询 | 轮询后台任务（`wait_seconds` 最高 `120s`，含 `idleSeconds` 与 `toolCallsCount`）；不传 `job_id` 时可单次等待全部活跃任务并列出 `activeSessions`。 |
| `codex_job_cancel` | 安全取消任务 | 取消排队中或运行中的任务并终止整棵子进程树（Windows 使用 Job Object，macOS/Linux 使用 `start_new_session` + `os.killpg`）。 |

## 核心特性

- **配额与重置时间感知路由**：自动判断 5 小时或 7 天窗口是否临近重置且存在富余配额（`use_it_or_lose_it`）、充裕、适中或即将耗尽，帮助主力 Agent 自动决定该用 `gpt-6.2-astra`（`xhigh`/`high`）还是保守省着用。
- **彻底规避 MCP 3 分钟超时与高频轮询**：深度审计或大 Diff 审查传入 `background: true` 立即返回 `jobId`，支持 `codex_job_status(wait_seconds=90–120, include_results=true)`（30–60s 宿主用 `20–45`）单次合并等待多个后台任务。
- **灵活超时与断点完整回收**：后台超时默认 `900s`/`1800s`（支持 `timeout_seconds: 0` 由 Agent 自主控制启停）；`background: true` 任务默认可续接（`ephemeral: false`），且超时/取消时直接返回完整的 `agentMessages` 与 `activityLog`，无需翻找本地日志。
- **多模态传图与 Profile 复用**：通过 `codex_exec` 的 `images`（`-i`）直接把 UI 截图、报错截图喂给 GPT 看；通过 `profile`（`-p`）直接复用 `~/.codex` 中的个人配置档。
- **多轮上下文续接与会话可见性**：首轮传 `ephemeral: false` 获取 `sessionId`，后续带上 `session_id` 即可保留完整上下文与 Prompt 缓存，随时可通过 `codex_job_status` 查看当前活跃会话。
- **全平台深度兼容**：纯 Python 3.10+ 标准库（无需 `pip install`）；Windows 下自动直连原生 `codex.exe`（支持 x64 与 ARM64）并处理 UTF-8 / 本地编码（如 GBK/CP936）回退；全平台支持完整进程树清理。

## 兼容性与 Antigravity 独占功能

| 组件 | 适用范围 | 说明 |
| :--- | :--- | :--- |
| `server/codex_mcp_server.py` | **全平台 / 全 Agent 通用（Win/macOS/Linux）** | 标准 JSON-RPC 2.0 MCP stdio 服务端，提供全部 6 个工具。 |
| `skills/codex-delegate/`（`SKILL.md` + `references/playbook.md`） | **跨 Agent 通用**（含 Antigravity 备注） | 标准 `SKILL.md` 工作流，兼容 Antigravity、Claude Code、Cursor、Pi 等；Antigravity 专属细节已在文中单独标注。 |
| `rules/AGENTS.md` | **跨 Agent 通用**（含 Antigravity 备注） | 精简常驻规则，兼容支持 `AGENTS.md` 的各类 Agent。 |
| `plugin.json` 与 `mcp_config.json` | **Antigravity 独占** | 使用 Antigravity 插件清单与 `${PLUGIN_ROOT}` 变量（自动挂载为 `codex-bridge_codex-bridge`）。 |
| `.claude-plugin/`（`plugin.json`、`marketplace.json`）与 `.mcp.json` | **Claude Code 独占** | 标准 Claude Code 插件与市场清单，使用 `${CLAUDE_PLUGIN_ROOT}` 自动加载 MCP 服务与 `codex-delegate` 技能。 |
| `agents/codex_worker.md` | **Antigravity 独占** | 使用 Antigravity 子代理 frontmatter 规范（`subagent: true`、`call_mcp_tool`、`view_file` 等）。 |
| `RefreshMcpServers` 热重载接口（见 `AGENTS.md`） | **Antigravity 独占** | 仅用于在运行中的 Antigravity IDE 内单独热重载本 MCP 服务。 |

---

## 前置条件

1. 已安装并登录 **OpenAI Codex CLI**：
   ```bash
   codex --version       # 期望输出：codex-cli <版本号>（如 0.172.0）
   codex login status    # 期望输出：Logged in using ChatGPT
   ```
2. 系统 `PATH` 中包含 **Python 3.10+**（纯标准库实现，无需安装第三方包）：
   ```bash
   python --version      # 期望输出：Python 3.10+（如 3.11.5）
   ```

---

## 安装与配置

请根据你使用的客户端选择对应的接入步骤：

### 1. Antigravity（开箱即用一体化插件）

Antigravity 会把 **MCP 服务、Skill（`codex-delegate`）、Rule（`rules/AGENTS.md`）以及子代理（`codex_worker`）** 作为一个完整插件自动全部加载。

- **方式 A — 直接克隆到 Antigravity 插件目录**（最简单）：
  - **macOS / Linux**：
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows（PowerShell）**：
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
    *（Windows 自带 PowerShell 5.1 不会为 `git.exe` 等原生命令展开 `~`，可能误建名为 `~` 的文件夹，请始终使用 `$env:USERPROFILE`。）*
  - **Windows（`cmd`）**：
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```

- **方式 B — 克隆到自定义目录并注册**（推荐习惯集中管理仓库的开发者使用）：
  1. 先将仓库克隆到你习惯的目录：
     ```bash
     git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
     ```
  2. 在 `~/.gemini/config/plugins.json` 中注册该目录：
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
     或者直接链接到 `~/.gemini/config/plugins/codex-bridge`：
     - **macOS / Linux**：
       ```bash
       ln -s /path/to/codex-bridge ~/.gemini/config/plugins/codex-bridge
       ```
     - **Windows（cmd）**：
       ```cmd
       mklink /J "%USERPROFILE%\.gemini\config\plugins\codex-bridge" "C:\path\to\codex-bridge"
       ```

`mcp_config.json` 已使用 `${PLUGIN_ROOT}/server/codex_mcp_server.py`，在 Antigravity 中无需手改任何路径。

---

### 2. Claude Code（原生插件安装推荐 / 手动 CLI 注册）

本项目已内置符合官方规范的 `.claude-plugin/plugin.json`、`.claude-plugin/marketplace.json` 与 `.mcp.json`（已通过 `claude plugin validate` 校验）。

- **方式 A — 作为 Claude Code 原生插件安装（推荐，自动配好 MCP + Skill）**：
  - **一步安装（Claude Code 2.1.275 及以上）**：
    ```text
    /plugin install codex-bridge --marketplace longpi233/codex-bridge
    ```
  - **或分步安装（兼容支持 `/plugin` 的 Claude Code 版本）**：
    ```text
    /plugin marketplace add longpi233/codex-bridge
    /plugin install codex-bridge@codex-bridge
    /reload-plugins
    ```
  - **本地开发 / 从已克隆目录临时加载**：
    ```bash
    claude --plugin-dir /path/to/codex-bridge
    ```
  *（无论从市场安装还是 `--plugin-dir` 加载，都会自动激活 `codex-bridge` MCP 服务与 `codex-delegate` 技能；同时会扫入 `agents/codex_worker.md`，但该文件包含 Antigravity 专属 frontmatter 工具名，在 Claude Code 中请由主 Agent 搭配 `codex-delegate` 直接调用 `codex-bridge` 工具，不要调用 `codex_worker`。）*

- **方式 B — 手动 CLI 注册（`claude mcp add-json` + Skill）**：
  1. **克隆仓库**：
     ```bash
     git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
     ```
  2. **注册并校验 MCP 服务**：
     ```bash
     claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
     claude mcp get codex-bridge
     ```
     *（Windows 下路径请使用正斜杠，如 `C:/path/to/codex-bridge/server/codex_mcp_server.py`；`claude mcp get` 期望看到 `Status: √ Connected`；如需全局生效可在 `codex-bridge` 前加上 `-s user`。注：在 Claude Code 2.1.332 等版本中 `claude mcp add ... -- python -u ...` 会直接报错 `error: unknown option '-u'`，请改用 `add-json`，且切勿去掉 `-u`，否则管道 stdout 块缓冲会导致客户端卡死。）*
  3. **安装 `codex-delegate` Skill 与 Rule（可选）**：
     - **全局安装**：将 `skills/codex-delegate` 链接或复制到 `~/.claude/skills/codex-delegate`（macOS/Linux：`ln -s /path/to/codex-bridge/skills/codex-delegate ~/.claude/skills/codex-delegate`；Windows `cmd`：`mklink /J "%USERPROFILE%\.claude\skills\codex-delegate" "C:\path\to\codex-bridge\skills\codex-delegate"`）。
     - **单项目安装**：复制到 `<你的项目>/.claude/skills/codex-delegate`。
     - **Rule**：将 [`rules/AGENTS.md`](./rules/AGENTS.md) 追加到 `~/.claude/CLAUDE.md`（或项目的 `CLAUDE.md`）。

---

### 3. Claude Desktop（macOS / Windows 桌面客户端）

Claude Desktop 支持直接通过 GitHub 仓库添加插件市场（**Add marketplace**）、上传本地干净的 `.plugin` / `.zip` 插件包，以及手动配置 `claude_desktop_config.json` 三种接入方式。

#### 方式 A：通过 GitHub 市场同步安装（最快 — 无需本地克隆或打包）

1. 打开 Claude Desktop，进入 **Customize（自定义）** → **Plugins（插件）** → **+ Add** → **Add marketplace**。
2. 在 **URL** 栏输入 `longpi233/codex-bridge`（或 `https://github.com/longpi233/codex-bridge.git`），点击 **Sync**。
3. 同步完成后安装 `codex-bridge`，即可一步启用全部 6 个基于 `${CLAUDE_PLUGIN_ROOT}` 的 MCP 工具并安装 `codex-delegate` 技能。
- *（注：与 Claude Code 的市场安装一致，此方式同样会扫入包含 Antigravity 专属 frontmatter 的 `agents/codex_worker.md`——请直接通过主 Agent 搭配 `codex-delegate` 调用工具，不要调用 `codex_worker`。若因桌面端未继承 `PATH` 中的 `python` 导致 6 个工具未出现，请改用下方**方式 C**。）*

#### 方式 B：上传本地 `.plugin` 插件包（纯净包，不含 Antigravity 专属文件）

1. **克隆仓库并打入干净的 Claude 插件包**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git
   cd codex-bridge
   python scripts/pack_claude_plugin.py
   ```
   该脚本会生成 `dist/codex-bridge.plugin`，仅包含 `.claude-plugin/plugin.json`、`.mcp.json`、`server/codex_mcp_server.py`、`skills/codex-delegate/` 与 `LICENSE`（自动排除 `agents/codex_worker.md` 等 Antigravity 专用文件）。

2. **在 Claude Desktop 中上传**：
   - 打开 **Settings…（设置）** → **Customize（自定义）** → **Plugins（插件）** → **Upload local plugin**。
   - 拖入或选择 `dist/codex-bridge.plugin`。
   - 上传启用后，会一步自动注册基于本地 `stdio`（`${CLAUDE_PLUGIN_ROOT}`）的全部 6 个 MCP 工具并安装 `codex-delegate` Skill。
   - **若 6 个工具未出现**：插件包内的 `.mcp.json` 使用裸 `"command": "python"`；如果桌面端 GUI 进程未继承终端 `PATH`（或命中 Windows Store 的 `python` 存根），请改用下方**方式 C** 并填写 `python.exe` / `python3` 的绝对路径。

#### 方式 C：手动配置 `claude_desktop_config.json`（适合自定义 `python` 路径 / `env` 或仅装 MCP）

如果桌面端未继承终端 `PATH` 导致找不到 `python`，或需要显式指定 `CODEX_BIN` / `CODEX_HOME` / `CODEX_DEFAULT_MODEL` 等环境变量、或仅想接入 MCP 而不装插件包，可使用此方式：

1. **克隆仓库到本地**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **打开 Claude Desktop 的配置文件**：
   - 在 Claude Desktop 菜单中打开 **Settings…（设置）** → **Developer（开发者）** → **Edit Config（编辑配置）**，或直接编辑以下路径：
     - **Windows**：`%APPDATA%\Claude\claude_desktop_config.json`
     - **macOS**：`~/Library/Application Support/Claude/claude_desktop_config.json`

3. **在 `mcpServers` 中添加 `codex-bridge`**（桌面 GUI 应用通常不会继承终端 `PATH`，强烈建议**同时填写 `python` 与 `codex_mcp_server.py` 的绝对路径**，可通过 `where python` 或 `which python3` 查询）：
   - **Windows 示例**：
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
   - **macOS 示例**：
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

4. **彻底退出并重启 Claude Desktop**：
   - 仅关闭窗口不会生效，必须在系统托盘 / 菜单栏 **完全退出（Quit）** 后重新打开。
   - 若工具未出现，可在 **Settings → Developer → Open Logs Folder** 查看启动日志定位路径或 Python 环境问题。

---

### 4. Cursor、Windsurf、WorkBuddy 及其他 MCP 客户端（配置 MCP + 安装 Skill 与 Rule）

> **配置文件归属对照（切勿混用模板）**：
>
> | 客户端 | 配置文件 / 路径 | 路径变量 | 默认 server key → 工具名前缀 |
> | :--- | :--- | :--- | :--- |
> | **Antigravity** | `mcp_config.json`（内置） | `${PLUGIN_ROOT}` | `codex-bridge_codex-bridge`（`call_mcp_tool`） |
> | **Claude Code / Desktop 插件** | `.mcp.json`（内置） | `${CLAUDE_PLUGIN_ROOT}` | `codex-bridge` → `mcp__codex-bridge__<tool>` |
> | **WorkBuddy / Cursor / Windsurf** | `~/.workbuddy/mcp.json`、`.workbuddy/mcp.json`、`~/.cursor/mcp.json` | 仅限绝对路径 | `codex_bridge` → `mcp__codex_bridge__<tool>` |
> | **DSH（见第 5 节）** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | 绝对路径（YAML） | `codex-bridge` → `mcp__codex-bridge__<tool>` |
>
> **严禁**把 `mcp_config.json`（含 `${PLUGIN_ROOT}`）或 `.mcp.json`（含 `${CLAUDE_PLUGIN_ROOT}`）复制到 Cursor、WorkBuddy 或 DSH。实际前缀以客户端工具列表显示为准。

1. **克隆仓库**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **在客户端的 MCP 配置文件中添加 `codex-bridge`**（例如 `~/.cursor/mcp.json`、`.cursor/mcp.json`、Windows 用户级 `%USERPROFILE%\.workbuddy\mcp.json` 或项目级 `<项目>\.workbuddy\mcp.json`，以及 Windsurf 的 `mcp_config.json`；**DSH** 请直接看下方**第 5 节**）：

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
   - **Python 绝对路径**：请将 `"/path/to/python"` 替换为本机实际解释器路径（例如 Windows 用正斜杠 `"C:/Python311/python.exe"`，macOS/Linux 用 `"/usr/local/bin/python3"`；裸 `"python"` 仅在 GUI 继承终端 `PATH` 时可用）。
   - **针对短超时或未验证调用上限的宿主**：即便小改动同步 `codex_review` 实测也需 ~45 秒以上，因此在单次调用上限较短（30–60s）或尚未验证的宿主上（例如 WorkBuddy 中 `mcp.json` 的 `timeout` 仅控制连接启动超时而非单次工具调用上限），`codex_review` 及所有 `medium` 以上任务**必须**使用 `background: true`，且将 `codex_job_status` 的 `wait_seconds` 控制在 `20`–`45` 秒（除非宿主配置如 DSH 的 `toolCallTimeoutMs` 已确认调大）。另请注意：`jobId` 仅在当前服务端进程生命周期内有效，而 `sessionId`（`background: true` 默认持久化）由 Codex CLI 落盘保存，重启后仍可续接。

3. **在 WorkBuddy 中激活与信任（看到工具的必要步骤）**：
   - 写入 `%USERPROFILE%\.workbuddy\mcp.json`（或 `<项目>\.workbuddy\mcp.json`）后，**必须完全退出并重启 WorkBuddy**。
   - 打开 **连接器管理 → 右上角自定义连接器**，对 `codex_bridge` 点击 **信任**，确认状态灯变绿后 6 个 `mcp__codex_bridge__*` 工具才会正式注入（修改 `.py` 后同样需要重启生效）。

4. **安装 `codex-delegate` Skill 与 Rule**（推荐）：
   - **安装 Skill**：将 `skills/codex-delegate/` 复制或软链接到对应客户端的技能目录：
     - 通用跨 Agent 规范路径（Cursor / Pi / Codex 等）：`.agents/skills/codex-delegate` 或 `~/.agents/skills/codex-delegate`
     - Cursor / WorkBuddy 路径：`.cursor/skills/codex-delegate`、`~/.workbuddy/skills/codex-delegate` 或 `.codebuddy/skills/codex-delegate`
     - DeepSeek Harness (DSH) 路径：`~/.dsh/skills/codex-delegate`（注意：`.agents/skills/` 对 DSH 不生效）
   - **安装 Rule**：将 [`rules/AGENTS.md`](./rules/AGENTS.md) 合并到项目根目录的 `AGENTS.md`（或客户端规则目录，如 `.cursor/rules/`、`.codebuddy/rules/`）。

---

### 5. DeepSeek Harness (DSH)

DSH **不使用** JSON 格式的 `mcp.json`，其 MCP 服务通过 Cordis 补丁层注册，Skill 目录位于 `~/.dsh/skills/`。

1. **追加条目到 `~/.dsh/profiles/<profile>/cordis.patch.yml`**（顶层为 YAML 列表；先检查文件中是否已有同名 `serverName: codex-bridge` 以免与旧条目或包安装冲突）：
   ```yaml
   - insert:
       - id: codex-bridge-mcp
         name: '@deepseek-ai/dsh-mcp-client'
         config:
           serverName: codex-bridge
           transport: stdio
           command: 'C:\Python311\python.exe'      # 请写绝对路径：DSH 不会继承终端 PATH
           args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
           cwd: 'D:\tools\codex-bridge'
           toolCallTimeoutMs: 1800000              # 必填 — 见第 3 步说明
           failOnStartupError: true
   ```
   *（如果 DSH 的 `install_bundle` 因已有 profile 的 `pnpm` v10/v11 store 版本冲突报错 `ERR_PNPM_UNEXPECTED_STORE`，直接写入 `cordis.patch.yml` 即可绕过 pnpm。）*

2. **保存即热重载**：Loader 会热加载补丁，**无需重启 DSH**。6 个工具会以 `mcp__codex-bridge__<tool>`（连字符形式，与 Claude Code 一致）注册上线。

3. **必须设置 `toolCallTimeoutMs: 1800000`**：DSH 默认单次调用超时为 `60000` ms，会导致 `wait_seconds=90` 的 `codex_job_status` 轮询在 60 秒处被砍断报 `Error: Request timed out`；配置 `1800000` 后长轮询（实测 88.6s）可正常返回，否则请将 `wait_seconds` 控制在 `20`–`45`。

4. **超时后任务不会丢失**：宿主层的 RPC 超时**不会杀死 MCP 子进程或后台 Codex 任务**——再次调用 `codex_job_status` 即可取回已完成的完整结果。

5. **安装 Skill**：将 `skills/codex-delegate/` 复制到 `~/.dsh/skills/codex-delegate`（Windows 下为 `C:\Users\<用户名>\.dsh\skills\codex-delegate`）。

---

## 快速上手示例

接入完成后，可以直接这样对你的主力 Agent 说：

- *“查一下我现在的 Codex 配额和重置时间，推荐一下现在该用哪个 GPT 模型和推理强度。”*
- *“让 Codex（`gpt-6.2-astra`）用只读后台模式帮我审查一下当前未提交的代码改动，重点看并发和边界条件。”*
- *“用 `codex_exec` 把这张报错/UI 截图传给 GPT，结合 `src/App.tsx` 帮我排查问题。”*

## 可选环境变量

| 环境变量 | 说明 |
| :--- | :--- |
| `CODEX_BIN` | 当 `codex` / `codex.exe` 未在 `PATH` 中自动识别时，显式指定其可执行文件路径。 |
| `CODEX_HOME` | 自定义 Codex 状态与认证目录（默认为 `~/.codex`）。 |
| `CODEX_DEFAULT_MODEL` | 当未传 `model` 且未设 `profile` 时的可选默认模型 ID（未配置则直接交由 Codex CLI 自身默认模型决定）。 |
| `CODEX_BRIDGE_LOG_FILE` | 可选的结构化 JSONL 诊断日志文件路径（默认关闭，绝不写入 `stderr`）。 |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | 设为 `1` 时在 `codex_quota_status` 中返回未脱敏的 `account.email`（默认打码）。 |

## 运行测试

运行离线单元测试、并发/取消测试与 CLI 参数测试（不消耗任何模型配额）：

```bash
python tests/test_codex_bridge.py
```

运行包含真实 Codex CLI / `app-server` 的冒烟测试（使用 `gpt-6-luna` `low`，根据是否触发工具调用实测基线约消耗 2.3 万–11 万 input tokens；配额紧张时请跳过）：

```bash
python tests/test_codex_bridge.py --live
```

## 故障排查与服务端自检

如果客户端中未出现工具，可先不经任何客户端直接通过 stdio 验证服务端本身是否正常：

- **Windows（PowerShell）**：
  ```powershell
  $p = @'
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
  {"jsonrpc":"2.0","method":"notifications/initialized"}
  {"jsonrpc":"2.0","id":2,"method":"tools/list"}
  '@
  $p | python -u server/codex_mcp_server.py
  ```
- **macOS / Linux / bash**：
  ```bash
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | python -u server/codex_mcp_server.py
  ```

症状判读与处理建议：

| 现象 | 根因判断与处理 |
| :--- | :--- |
| **stdio 自检正常返回 2 行 JSON**（含 6 个工具），**但客户端中仍看不到工具** | 服务端健康，卡在客户端激活。**WorkBuddy**：完全退出并重启后在“自定义连接器”中点击信任；**Claude Desktop**：从托盘/菜单栏完全退出重开。 |
| **状态灯变红 / 启动失败** | 检查 JSON 语法、`python` 绝对路径（勿用裸 `"python"`）、`CODEX_BIN` / `CODEX_HOME`，或临时开启 `CODEX_BRIDGE_LOG_FILE` 排查请求日志。 |
| **自检无输出或报 traceback** | 检查 Python 版本（需 `3.10+`）及客户端启动日志。 |
| **自检卡住不退出也不输出** | 检查是否漏掉了 `-u` 参数（缺少 `-u` 会导致管道 stdout 块缓冲）。 |

## 目录结构

```text
codex-bridge/
├── .claude-plugin/
│   ├── plugin.json                    # Claude Code 插件清单
│   └── marketplace.json               # Claude Code 市场清单
├── .mcp.json                          # Claude Code MCP 配置（使用 ${CLAUDE_PLUGIN_ROOT}）
├── plugin.json                        # Antigravity 插件清单
├── mcp_config.json                    # Antigravity MCP 配置（使用 ${PLUGIN_ROOT}）
├── AGENTS.md                          # 供修改本仓库代码的 AI Agent 阅读的指南
├── README.md                          # 项目说明与配置文档（English）
├── README_CN.md                       # 项目说明与配置文档（简体中文）
├── LICENSE                            # MIT 开源协议
├── .gitignore
├── scripts/
│   └── pack_claude_plugin.py          # 从白名单打包干净的 dist/codex-bridge.plugin
├── server/
│   └── codex_mcp_server.py            # 跨平台、零依赖的 MCP stdio 服务端
├── skills/
│   └── codex-delegate/
│       ├── SKILL.md                   # 渐进式披露的 Codex 委派技能
│       └── references/
│           └── playbook.md            # 即复制即用的 MCP 参数调用示例
├── agents/
│   └── codex_worker.md                # Antigravity 专属子代理定义
├── rules/
│   └── AGENTS.md                      # 精简的委派规则
└── tests/
    └── test_codex_bridge.py           # 离线单元测试与可选 --live 测试套件
```

## 开源协议

本项目基于 [MIT License](./LICENSE) 开源。
