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

**`codex-bridge`** 是一个轻量、零第三方依赖的 **MCP 服务端**与**原生插件**（原生支持 **Antigravity**、**Claude Code / Claude Desktop** 与 **DeepSeek Harness**），让你常用的 AI 编程助手直接把深度推理、代码审计和 Git 差异审查委派给本地的 **OpenAI Codex CLI**（`codex`）。

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
- [开源协议](#开源协议)

---

## 核心特性

- **配额与重置时间感知**：实时读取你的 5 小时与 7 天 Codex 配额及重置时间，帮主力 Agent 自动判断什么时候放心上 `gpt-6.2-astra`，什么时候省着用。
- **深度审计不超时**：长时间的代码审查与大 Diff 分析自动走后台异步执行，无需干等或担心客户端超时中断。
- **多轮上下文续接**：保留 Codex 会话上下文，方便“审查 → 修改 → 复验”连续推进，不必每轮从头讲起。
- **多模态传图与配置复用**：支持直接把本地截图喂给 GPT 分析（`images`），也可直接复用 `~/.codex` 中的配置档（`profile`）。
- **零依赖全平台可用**：纯 Python 3.10+ 标准库实现，Windows、macOS 与 Linux 开箱即用。

## MCP 工具一览

| 工具名 | 功能简介 |
| :--- | :--- |
| `codex_quota_status` | 查询当前 5 小时 / 7 天 Codex 实时配额、重置时间，并给出模型与推理强度建议。 |
| `codex_list_models` | 列出你当前 Codex 账号可用的 GPT 模型及支持的推理强度。 |
| `codex_exec` | 执行非交互任务、代码审计或受限子任务，支持沙箱权限、传图、Profile、多轮续接与后台运行。 |
| `codex_review` | 以只读模式对未提交改动、分支差异、指定 Commit 或自定义关注点进行代码审查。 |
| `codex_job_status` | 查看或等待后台任务完成并收取结果，同时列出当前可续接的活跃会话。 |
| `codex_job_cancel` | 安全取消排队或运行中的后台任务并清理其子进程。 |

---

## 前置条件

1. 已安装并登录 **OpenAI Codex CLI**：
   ```bash
   codex --version
   codex login status    # 期望看到：Logged in using ChatGPT
   ```
2. 已安装 **Python 3.10+**：
   ```bash
   python --version
   ```

---

## 安装与部署

选择你正在使用的客户端：

- [1. Antigravity](#1-antigravity)
- [2. Claude Code 与 Claude Desktop](#2-claude-code-与-claude-desktop)
- [3. DeepSeek Harness](#3-deepseek-harness)
- [4. Cursor、Windsurf、WorkBuddy 及其他 MCP 客户端](#4-cursorwindsurfworkbuddy-及其他-mcp-客户端)

---

### 1. Antigravity

一键安装完整插件包，自动加载 MCP 服务、`codex-delegate` 技能、常驻规则以及 `codex_worker` 子代理（Antigravity CLI 与 App 插件自动同步）。

- **通过 Antigravity CLI 安装（`agy`，推荐）**：
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git
  agy plugin install ./codex-bridge
  ```
- **或直接克隆到 Antigravity 插件目录**：
  - **macOS / Linux**：
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
  - **Windows（PowerShell）**：
    ```powershell
    git clone https://github.com/longpi233/codex-bridge.git "$env:USERPROFILE\.gemini\config\plugins\codex-bridge"
    ```
  - **Windows（`cmd`）**：
    ```cmd
    git clone https://github.com/longpi233/codex-bridge.git "%USERPROFILE%\.gemini\config\plugins\codex-bridge"
    ```
- **或将已有目录注册到 `~/.gemini/config/plugins.json`**：
  ```json
  { "entries": [{ "path": "/path/to/parent-folder", "include_only": ["codex-bridge"] }] }
  ```

---

### 2. Claude Code 与 Claude Desktop

安装后自动启用全部 6 个 MCP 工具、`codex-delegate` 技能以及 Claude 原生的 `codex-worker` 子代理。

#### 方式 A：通过 GitHub 市场在线同步（推荐，便于后续同步更新）

- **Claude Desktop**：
  1. 打开 **Customize（自定义）** → **Plugins（插件）** → **Discover** → 点击 **`+`** *（鼠标悬停在 `+` 上会显示 **Add marketplace**）*。
  2. 输入 `longpi233/codex-bridge`，点击 **Sync**。
  3. 同步完成后安装 **`codex-bridge`** 即可。
- **Claude Code**：
  ```text
  # Claude Code 2.1.275 及以上
  /plugin install codex-bridge --marketplace longpi233/codex-bridge

  # 较早支持 /plugin 的版本
  /plugin marketplace add longpi233/codex-bridge
  /plugin install codex-bridge@codex-bridge
  /reload-plugins
  ```
  也可以直接加载本地克隆目录：`claude --plugin-dir /path/to/codex-bridge`。

#### 方式 B：上传预构建的 `.plugin` 插件包（Claude Desktop 离线方式）

1. 前往 [GitHub Releases](https://github.com/longpi233/codex-bridge/releases/latest) 下载 **`codex-bridge.plugin`** *（或克隆仓库后运行 `python scripts/pack_claude_plugin.py` 自行打包）*。
2. 在 Claude Desktop 打开 **Settings…（设置）** → **Customize（自定义）** → **Plugins（插件）** → **Upload local plugin**，拖入或选择 `codex-bridge.plugin`。

#### 手动配置（如需自定义 Python 路径或环境变量）

- **Claude Desktop**：打开 **Settings… → Developer → Edit Config**（Windows 为 `%APPDATA%\Claude\claude_desktop_config.json`，macOS 为 `~/Library/Application Support/Claude/claude_desktop_config.json`），按 [第 4 节](#4-cursorwindsurfworkbuddy-及其他-mcp-客户端) 的 JSON 模板填写，保存后彻底退出并重启 Claude Desktop。
- **Claude Code CLI**：
  ```bash
  git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
  claude mcp add-json codex-bridge '{"command":"python","args":["-u","/path/to/codex-bridge/server/codex_mcp_server.py"]}'
  ```
  *（如需全局生效，在 `codex-bridge` 前加上 `-s user`。）*

---

### 3. DeepSeek Harness

DSH 原生支持以 Cordis 插件包形式安装 `codex-bridge`。

- **通过 DSH 命令行安装（推荐）**：
  ```bash
  # 如使用其他 profile（例如 web / tui），请替换 desktop
  dsh plugin --profile desktop add github:longpi233/codex-bridge
  ```
  *（也可从本地目录安装：`dsh plugin --profile desktop add /path/to/codex-bridge`。）*
  1. 在 DSH 的「插件」页面启用 **`codex-bridge`**（或在 `~/.dsh/profiles/<profile>/package.json` 的 `dsh.profile.bundles` 中加入 `"codex-bridge"`）。
  2. *（可选）* 将 `skills/codex-delegate/` 复制到 `~/.dsh/skills/codex-delegate` 以启用配额感知委派技能。

- **或手动写入 `cordis.patch.yml`**：
  将以下片段追加到 `~/.dsh/profiles/<profile>/cordis.patch.yml` 并保存（DSH 会自动热重载，无需重启）：
  ```yaml
  - insert:
      - id: codex-bridge-mcp
        name: '@deepseek-ai/dsh-mcp-client'
        config:
          serverName: codex-bridge
          transport: stdio
          command: 'C:\Python311\python.exe'    # 填写本机 Python 绝对路径
          args: ['-u', 'D:\tools\codex-bridge\server\codex_mcp_server.py']
          cwd: 'D:\tools\codex-bridge'
          toolCallTimeoutMs: 1800000
          failOnStartupError: true
  ```

---

### 4. Cursor、Windsurf、WorkBuddy 及其他 MCP 客户端

1. **克隆仓库**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```
2. **在客户端的 MCP 配置中添加 `codex_bridge`**（例如 `~/.cursor/mcp.json`、`%USERPROFILE%\.workbuddy\mcp.json`、Windsurf 的 `mcp_config.json` 等）：
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
   - 请将 `"/path/to/python"` 替换为本机 Python 可执行文件的完整路径（例如 Windows 用 `C:/Python311/python.exe`，macOS/Linux 用 `/usr/local/bin/python3`）。
   - **WorkBuddy**：保存 `mcp.json` 后需彻底退出并重启 WorkBuddy，然后进入 **连接器管理 → 右上角自定义连接器**，对 `codex_bridge` 点击 **信任**。
3. **安装 Skill 与 Rule（推荐）**：
   - **Skill**：将 `skills/codex-delegate/` 复制或软链接到客户端技能目录（如 `~/.agents/skills/codex-delegate`、`.cursor/skills/codex-delegate`、`~/.workbuddy/skills/codex-delegate` 或 `.codebuddy/skills/codex-delegate`）。
   - **Rule**：将 [`rules/AGENTS.md`](./rules/AGENTS.md) 合并到项目根目录 `AGENTS.md` 或客户端规则目录。

---

## 快速上手

安装完成后，可以直接这样对你的主力 Agent 说：

- *“查一下我现在的 Codex 配额和重置时间，推荐一下现在该用哪个 GPT 模型和推理强度。”*
- *“让 Codex（`gpt-6.2-astra`）用只读后台模式审查一下我当前未提交的代码改动，重点找边界条件和并发问题。”*
- *“用 `codex_exec` 把这张 UI 截图发给 GPT，结合 `src/App.tsx` 帮我排查对齐问题。”*

---

## 环境变量

所有环境变量均为可选：

| 环境变量 | 说明 |
| :--- | :--- |
| `CODEX_BIN` | 显式指定 `codex` / `codex.exe` 路径（未加入 `PATH` 时使用）。 |
| `CODEX_HOME` | 自定义 Codex 认证与状态目录（默认为 `~/.codex`）。 |
| `CODEX_DEFAULT_MODEL` | 未传 `model` 与 `profile` 时的默认模型 ID。 |
| `CODEX_BRIDGE_PYTHON` | 为 DSH 原生插件包显式指定 Python 路径。 |
| `CODEX_BRIDGE_LOG_FILE` | 填写文件路径即可开启可选的 JSONL 诊断日志。 |
| `CODEX_BRIDGE_INCLUDE_EMAIL` | 设为 `1` 时在配额结果中显示完整邮箱（默认脱敏）。 |

---

## 故障排查

如果客户端里没有出现工具，可以先直接测试服务端本身是否正常工作：

- **Windows（PowerShell）**：
  ```powershell
  $p = @'
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
  {"jsonrpc":"2.0","method":"notifications/initialized"}
  {"jsonrpc":"2.0","id":2,"method":"tools/list"}
  '@
  $p | python -u server/codex_mcp_server.py
  ```
- **macOS / Linux**：
  ```bash
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | python -u server/codex_mcp_server.py
  ```

- **正常返回 2 行 JSON（包含全部 6 个工具）**：说明服务端本身正常，请检查客户端配置文件路径、改为填写 Python 完整路径并完全重启客户端（WorkBuddy 需在自定义连接器中点击**信任**）。
- **卡住无任何输出**：请检查参数列表中是否保留了 `-u`。

---

## 运行测试

```bash
# 离线测试套件（不消耗任何模型配额）
python tests/test_codex_bridge.py

# 使用本机 Codex CLI 运行真实冒烟测试
python tests/test_codex_bridge.py --live
```

---

## 开源协议

本项目基于 [MIT License](./LICENSE) 开源。
