# Codex GPT Bridge (`codex-bridge`)

<p align="center">
  <img src="./assets/logo.png" alt="codex-bridge logo" width="220" />
</p>

<p align="center">
  <a href="./README.md">English</a> | <strong>简体中文</strong>
</p>

<p align="center">
  <code>Python 3.10+</code> · <code>零外部依赖</code> · <code>MCP stdio</code> · <code>Windows / macOS / Linux</code> · <code>MIT License</code>
</p>

> **受够了 GPT 动不动就防御性拉满、打官腔、摆架子？已经忍无可忍亲自下场和 GPT 扯皮了吗？**
>
> 换个思路，让 **MCP** 来替你受气：把那个可爱又善解人意的 **Gemini**（或者任何你顺手的 Claude / 主力 Agent）推到台前，由它去和后台的 GPT 沟通对线！你照样白嫖 GPT 强悍的深度推理与代码审计能力，而所有咬文嚼字、参数对齐、长篇大论的“非人类输出”，全交给贴心的主力 Agent 消化转译——**从此再也不用担心 GPT 不说人话了。**

**`codex-bridge`** 是一个跨平台、零第三方依赖的 **MCP stdio 服务端**与**原生三端插件**（支持 **Claude Code / Claude Desktop**、**Antigravity** 与 **DeepSeek Harness / DSH**），可在 Windows、macOS 与 Linux 上把各类 AI 编程助手桥接到你本地的 **OpenAI Codex CLI**（`codex`）。

---

## 目录导航

- [核心特性](#核心特性)
- [MCP 工具一览](#mcp-工具一览)
- [前置条件](#前置条件)
- [安装与部署](#安装与部署)
- [快速上手](#快速上手)
- [环境变量](#环境变量)
- [故障排查](#故障排查)
- [运行测试](#运行测试)
- [目录结构](#目录结构)
- [开源协议](#开源协议)

---

## 核心特性

- **配额与重置时间感知路由**：实时查询 `codex app-server` 的 5 小时与 7 天限额窗口，自动识别 `use_it_or_lose_it`、`abundant`、`moderate`、`conserve` 等状态，帮主力 Agent 自动选择合适的模型与推理强度。
- **彻底规避 MCP 客户端超时**：深度审计或大 Diff 审查通过 `background: true` 后台运行，使用 `codex_job_status` 单次合并收集多个活跃任务，并提供分档轮询建议（180s+ 宿主用 `90–120s`；30–60s 宿主用 `20–45s`）。
- **断点可续接与完整状态回收**：后台任务默认落盘持久化（`ephemeral: false`），中断或暂停后可通过 `session_id` 无缝续接完整上下文并复用 Prompt 缓存；超时或取消时直接返回捕获的 `agentMessages` 与 `activityLog`。
- **多模态传图与 Profile 复用**：支持通过 `codex_exec` 的 `images`（`-i`）传入本地截图，或通过 `profile`（`-p`）直接复用 `~/.codex` 中的个人配置档。
- **零依赖全平台兼容**：纯 Python 3.10+ 标准库实现；Windows 下自动定位原生 `codex.exe`（支持 x64/ARM64）并兼容 UTF-8 / 本地编码（如 GBK/CP936）输出；全平台支持完整子进程树清理。

## MCP 工具一览

| 工具名 | 用途 | 核心能力 |
| :--- | :--- | :--- |
| `codex_quota_status` | 实时配额与路由 | 查询实时 5h/7d 窗口、重置时间、配额盈余比与 10 档调度建议（默认对 `account.email` 脱敏；离线时自动降级读取本地会话日志）。 |
| `codex_list_models` | 模型发现 | 列出本地 Codex CLI 可用的 GPT 模型（如 `gpt-6.2-sol`、`gpt-6.2-astra`）及支持的推理强度（`low` → `ultra`），自动翻页拉取全部上游模型。 |
| `codex_exec` | 非交互执行 | 预先校验 `cwd`，支持 `sandbox`、`profile`（`-p`）、`images`（`-i`）、`session_id` 多轮续接、`background: true` 与 `request_id` 幂等去重；上游未返回用量时返回 `usageUnavailable: true`。 |
| `codex_review` | Git 差异审查 | 只读审查 `--uncommitted`、`--base <branch>`、`--commit <sha>` 或自定义 `focus`，支持 `profile` 与工作区变更检测（因上游 `codex review` 不回传 token 计数，固定返回 `usageUnavailable: true`）。 |
| `codex_job_status` | 任务与会话查询 | 轮询后台任务（`wait_seconds`、`idleSeconds`、`toolCallsCount`），省略 `job_id` 时可单次等待全部活跃任务并列出 `activeSessions`。 |
| `codex_job_cancel` | 安全取消任务 | 取消排队或运行中的任务并终止整棵子进程树（Windows 使用 Job Object；POSIX 使用进程组 `SIGTERM`/`SIGKILL`）。 |

---

## 前置条件

1. 已安装并登录 **OpenAI Codex CLI**：
   ```bash
   codex --version       # 期望输出：codex-cli <版本号>
   codex login status    # 期望输出：Logged in using ChatGPT
   ```
2. 系统 `PATH` 中包含 **Python 3.10+**：
   ```bash
   python --version      # 期望输出：Python 3.10+
   ```

---

## 安装与部署

按**专用原生插件 → 通用 MCP 客户端**及常见使用频率排序，点击直达对应客户端：

- [1. Claude Code 与 Claude Desktop](#1-claude-code-与-claude-desktop) — 原生插件、Release `.plugin`、GitHub 市场同步与 CLI
- [2. Antigravity](#2-antigravity) — 开箱即用一体化插件（MCP + Skill + Rule + `codex_worker` 子代理）
- [3. DeepSeek Harness](#3-deepseek-harness) — DSH 原生插件包或 `cordis.patch.yml`
- [4. 通用 MCP 客户端](#4-通用-mcp-客户端) — Cursor、Windsurf、WorkBuddy 与通用 JSON 手动配置

---

### 1. Claude Code 与 Claude Desktop

本仓库内置符合官方规范的 `.claude-plugin/plugin.json`、`.claude-plugin/marketplace.json` 与 `.mcp.json`（已通过 `claude plugin validate` 校验）。

#### Claude Desktop

1. **推荐 — 从 [GitHub Releases](https://github.com/longpi233/codex-bridge/releases/latest) 下载 `.plugin` 插件包上传**：
   - 前往 Release 附件下载 **`codex-bridge.plugin`** *（已剔除 Antigravity 专属文件，离线可用；也可在本地克隆后运行 `python scripts/pack_claude_plugin.py` 构建）*。
   - 在 Claude Desktop 打开 **Settings…（设置）** → **Customize（自定义）** → **Plugins（插件）** → **Upload local plugin**，拖入或选择 `codex-bridge.plugin`。
2. **或直接通过 GitHub 市场在线同步**：
   - 打开 **Customize（自定义）** → **Plugins（插件）** → **+ Add** → **Add marketplace**。
   - 在 **URL** 填写 `longpi233/codex-bridge` 并点击 **Sync**，随后安装 `codex-bridge`。
3. **若 6 个工具未出现** *（桌面 GUI 进程未继承终端 `PATH` 或命中 Windows Store 存根）*：
   - 打开 **Settings… → Developer → Edit Config**（Windows 为 `%APPDATA%\Claude\claude_desktop_config.json`，macOS 为 `~/Library/Application Support/Claude/claude_desktop_config.json`），直接参考下方 [第 4 节通用 MCP 客户端](#4-通用-mcp-客户端) 的 JSON 模板填入 **`python` 绝对路径**，保存后在系统托盘 / 菜单栏**彻底退出（Quit）并重启** Claude Desktop。

#### Claude Code

- **原生插件安装（推荐）**：
  ```text
  # Claude Code 2.1.275+
  /plugin install codex-bridge --marketplace longpi233/codex-bridge

  # 或分步安装（兼容所有带 /plugin 命令的版本）
  /plugin marketplace add longpi233/codex-bridge
  /plugin install codex-bridge@codex-bridge
  /reload-plugins
  ```
  也可直接加载本地仓库：`claude --plugin-dir /path/to/codex-bridge`。
- **手动 CLI 注册** *（请使用 `add-json`；在 `2.1.332` 等版本中 `claude mcp add ... -- python -u ...` 会报错 `unknown option '-u'`）*：
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
  claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
  claude mcp get codex-bridge   # 期望输出：Status: √ Connected
  ```
  *（在 `codex-bridge` 前加 `-s user` 可全局注册；Skill 与 Rule 手动安装请参考 [第 4 节](#4-通用-mcp-客户端)，对应路径为 `~/.claude/skills/codex-delegate` 与 `~/.claude/CLAUDE.md`。）*

> **内置组件说明**：无论是上传 `.plugin` 插件包，还是通过 GitHub 市场 / `--plugin-dir` 安装，都会一并启用全部 6 个 MCP 工具、`codex-delegate` 技能以及 Claude 原生的 `codex-worker` 子代理（`claude/agents/codex-worker.md`，与 Antigravity 专用的 `agents/codex_worker.md` 互不冲突）。

---

### 2. Antigravity

Antigravity 会自动将 **MCP 服务（`codex-bridge_codex-bridge`）、`codex-delegate` Skill、`rules/AGENTS.md` 规则以及 `codex_worker` 子代理**作为一体化插件加载。

- **方式 A — 直接克隆到 Antigravity 插件目录**：
  - **macOS / Linux**：
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows（PowerShell）** *（PowerShell 5.1 不会为 `git.exe` 展开 `~`，请使用 `$env:USERPROFILE`）*：
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
  - **Windows（`cmd`）**：
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```
- **方式 B — 克隆到其他目录并在 `~/.gemini/config/plugins.json` 中注册**：
  ```json
  { "entries": [{ "path": "/path/to/parent-folder", "include_only": ["codex-bridge"] }] }
  ```

---

### 3. DeepSeek Harness

DSH 不使用 JSON 格式的 `mcp.json`，而是通过 Cordis 原生插件包（`package.json` + `cordis.patch.yml`）或 profile 补丁层注册 MCP 服务。

- **方式 A — 作为 DSH 原生插件包安装（推荐）**：
  1. 将仓库克隆到固定目录（`git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge`）。
  2. 通过 DSH 插件管理（`install_bundle`）指向该目录即可，插件包会自动定位 Python（或 `CODEX_BRIDGE_PYTHON`）与 `codex_mcp_server.py`、配置 `toolCallTimeoutMs: 1800000`，并在检测到已有 `codex-bridge` 行时自动禁用自身避免冲突。
  3. 将 `skills/codex-delegate/` 复制到 `~/.dsh/skills/codex-delegate`（`.agents/skills/` 对 DSH 不生效）。

- **方式 B — 手动写入 Profile 补丁层** *（若旧 profile 因 pnpm v10/v11 报错 `ERR_PNPM_UNEXPECTED_STORE`，可用此方式绕过 pnpm）*：
  在 `~/.dsh/profiles/<profile>/cordis.patch.yml` 追加（先确认无重复 `serverName: codex-bridge`），保存即热重载生效：
  ```yaml
  - insert:
      - id: codex-bridge-mcp
        name: '@deepseek-ai/dsh-mcp-client'
        config:
          serverName: codex-bridge
          transport: stdio
          command: 'C:\Python311\python.exe'    # 必须填绝对路径
          args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
          cwd: 'D:\tools\codex-bridge'
          toolCallTimeoutMs: 1800000            # 必填：DSH 默认 60000ms 会截断长轮询
          failOnStartupError: true
  ```
  > DSH 默认 `60000` ms 超时会截断长轮询，但后台 Codex 任务仍在运行，再次调用 `codex_job_status` 即可取回结果；建议配置 `toolCallTimeoutMs: 1800000`，或将 `wait_seconds` 控制在 `20–45`。

---

### 4. 通用 MCP 客户端

适用于 **Cursor**、**Windsurf**、**WorkBuddy** 及手动配置 **Claude Desktop** 的用户。

> **切勿**把仓库内的 `mcp_config.json`（含 `${PLUGIN_ROOT}`）或 `.mcp.json`（含 `${CLAUDE_PLUGIN_ROOT}`）直接复制到这些客户端——通用宿主无法解析插件路径变量，且桌面端 GUI 常不继承终端 `PATH`。

1. **克隆仓库**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```
2. **在客户端配置中添加 `codex_bridge`**（例如 `~/.cursor/mcp.json`、`%USERPROFILE%\.workbuddy\mcp.json` / `.workbuddy/mcp.json`、Windsurf 的 `mcp_config.json` 或 Claude Desktop 的 `claude_desktop_config.json`）：
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
   - 请将 `"/path/to/python"` 替换为真实解释器路径（Windows 建议用正斜杠如 `C:/Python311/python.exe`，macOS/Linux 如 `/usr/local/bin/python3`）。
   - **WorkBuddy 激活步骤**：保存 `mcp.json` 后**必须完全退出并重启 WorkBuddy**，进入 **连接器管理 → 右上角自定义连接器** 对 `codex_bridge` 点击 **信任**，待状态灯变绿后 6 个工具才会注入。
   - **短超时或未验证调用上限的宿主** *（如 WorkBuddy）*：即便单 commit 同步 `codex_review` 实测也需 ~45s+，因此建议对 `codex_review` 与所有 `medium` 以上任务强制使用 `background: true`，并将 `wait_seconds` 控制在 `20–45`。
3. **安装 Skill 与 Rule**（推荐）：
   - **Skill**：将 `skills/codex-delegate/` 复制或软链接到对应目录（`~/.agents/skills/codex-delegate`、`.cursor/skills/codex-delegate`、`~/.workbuddy/skills/codex-delegate`、`.codebuddy/skills/codex-delegate` 或 `~/.dsh/skills/codex-delegate`）。
   - **Rule**：将 [`rules/AGENTS.md`](./rules/AGENTS.md) 合并到项目根目录 `AGENTS.md` 或客户端规则目录。

| 客户端 | 默认 server key | 暴露的工具名格式 |
| :--- | :--- | :--- |
| **Antigravity** | `codex-bridge_codex-bridge` | `call_mcp_tool`（`ServerName` 参数） |
| **Claude Code / Desktop / DSH** | `codex-bridge` | `mcp__codex-bridge__<tool>` |
| **WorkBuddy / Cursor** | `codex_bridge` | `mcp__codex_bridge__<tool>` |

---

## 快速上手

接入完成后，可以直接这样对主力 Agent 说：

- *“查一下我现在的 Codex 配额和重置时间，推荐现在该用哪个 GPT 模型和推理强度。”*
- *“让 Codex（`gpt-6.2-astra`）用只读后台模式审查当前未提交的代码改动，重点看并发和边界条件。”*
- *“用 `codex_exec` 把这张截图传给 GPT，结合 `src/App.tsx` 帮我排查对齐问题。”*

---

## 环境变量

| 环境变量 | 说明 |
| :--- | :--- |
| `CODEX_BIN` | 显式指定 `codex` / `codex.exe` 路径（未在 `PATH` 中识别时使用）。 |
| `CODEX_HOME` | 自定义 Codex 认证与状态目录（默认为 `~/.codex`）。 |
| `CODEX_DEFAULT_MODEL` | 未传 `model` 与 `profile` 时的默认模型 ID（未设置则遵循 Codex CLI 默认配置）。 |
| `CODEX_BRIDGE_LOG_FILE` | 可选的结构化 JSONL 诊断日志文件路径（默认关闭，不写入 `stderr`）。 |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | 设为 `1` 时在 `codex_quota_status` 中返回未脱敏的 `account.email`。 |
| `CODEX_BRIDGE_PYTHON` | 为 DSH 原生插件包（`cordis.patch.yml`）显式指定 Python 路径。 |

---

## 故障排查

如果客户端里没有出现工具，请先直接通过 stdio 自检服务端本身：

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

| 现象 | 原因判断与处理 |
| :--- | :--- |
| **自检返回 2 行 JSON**（`initialize` + 6 个工具的 `tools/list`），**但客户端中看不到工具** | 服务端正常，问题在客户端激活或路径配置。**WorkBuddy**：彻底退出重启并在自定义连接器中点击信任；**Claude Desktop**：从托盘彻底退出重开，或改用 [第 4 节](#4-通用-mcp-客户端) 填写 Python 绝对路径。 |
| **状态灯变红 / 启动报错** | 检查 JSON/YAML 语法、`python` 绝对路径、`CODEX_BIN` / `CODEX_HOME`，或临时开启 `CODEX_BRIDGE_LOG_FILE` 排查。 |
| **自检卡住无输出** | 确认参数包含 `-u`（缺少 `-u` 会导致 stdout 块缓冲）。 |

---

## 运行测试

```bash
# 离线单元测试、并发/取消与畸形报文测试（零配额消耗）
python tests/test_codex_bridge.py

# 真实 Codex CLI / app-server 冒烟测试（gpt-6-luna low，约消耗 2.3 万–11 万 input tokens）
python tests/test_codex_bridge.py --live
```

---

## 目录结构

```text
codex-bridge/
├── assets/logo.png                    # 项目与多端插件图标
├── .claude-plugin/                    # Claude Code / Desktop 插件与市场清单
├── .mcp.json                          # Claude 插件 MCP 配置（${CLAUDE_PLUGIN_ROOT}）
├── plugin.json                        # Antigravity 插件清单
├── mcp_config.json                    # Antigravity MCP 配置（${PLUGIN_ROOT}）
├── package.json                       # DSH 原生插件包清单
├── cordis.patch.yml                   # DSH 原生 Cordis 补丁定义
├── locale/                            # DSH 本地化元数据（en.json, zh.json）
├── server/codex_mcp_server.py         # 跨平台、零依赖的 MCP stdio 服务端
├── skills/codex-delegate/             # 跨 Agent 委派工作流与调用手册
├── claude/agents/codex-worker.md      # Claude Code / Desktop 原生子代理定义
├── agents/codex_worker.md             # Antigravity 专属子代理定义
├── rules/AGENTS.md                    # 精简的常驻委派规则
├── scripts/pack_claude_plugin.py      # 打包 Claude Desktop 专用 dist/codex-bridge.plugin
└── tests/test_codex_bridge.py         # 离线与可选 --live 测试套件
```

---

## 开源协议

本项目基于 [MIT License](./LICENSE) 开源。
