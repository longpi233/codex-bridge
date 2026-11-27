# Codex GPT Bridge (`codex-bridge`)

[English](./README.md) | 简体中文

`Python 3.10+` · `零外部依赖` · `MCP stdio` · `Windows / macOS / Linux` · `MIT License`

> **受够了 GPT 动不动就防御性拉满、打官腔、摆架子？已经忍无可忍亲自下场和 GPT 扯皮了吗？**
>
> 换个思路，让 **MCP** 来替你受气：把那个可爱又善解人意的 **Gemini**（或者任何你顺手的 Claude / 主力 Agent）推到台前，由它去和后台的 GPT 沟通对线！你照样白嫖 GPT 强悍的深度推理与代码审计能力，而所有咬文嚼字、参数对齐、长篇大论的“非人类输出”，全交给贴心的主力 Agent 消化转译——**从此再也不用担心 GPT 不说人话了。**

这是一个跨平台、零第三方依赖的 **MCP stdio 服务端**与 **Antigravity 插件**，可在 **Windows、macOS 和 Linux** 上将各类 AI 编程助手（**Antigravity、Claude Code、Cursor、Windsurf 及任意支持 MCP stdio 的客户端**）桥接到你本地的 OpenAI Codex CLI（`codex`）。

---

## 暴露的 MCP 工具

| 工具名 | 用途 | 核心能力 |
| :--- | :--- | :--- |
| `codex_quota_status` | 实时配额与路由 | 查询 `codex app-server` 获取 5 小时/7 天双窗口限额、精确重置时间、配额盈余比，并生成 8 档模型与推理强度建议（离线时自动降级读取本地会话日志）。 |
| `codex_list_models` | 模型发现 | 列出当前本地 Codex CLI 可用的 GPT 模型（如 `gpt-6.2-sol`、`gpt-6.2-astra`）及支持的推理强度（`low` → `ultra`），支持分页与 `include_hidden`。 |
| `codex_exec` | 非交互执行 | 预先校验 `cwd`，支持自定义 `sandbox`、`-p` `profile`、`-i` `images`（多模态传图）、`ephemeral: false` + `session_id` 多轮续接，以及 `background: true` 后台运行。 |
| `codex_review` | Git 差异审查 | 以严格 `read-only` 模式审查 `--uncommitted`、`--base <branch>`、`--commit <sha>` 或自定义 `focus` 审查重点，支持 `profile` 及审查期间工作区变更检测。 |
| `codex_job_status` | 任务与会话查询 | 轮询后台任务（`wait_seconds` 最高 `120s`，含 `idleSeconds` 与 `toolCallsCount`）、支持 `request_id` 幂等去重；不传 `job_id` 时可单次等待全部活跃任务并列出 `activeSessions`。 |
| `codex_job_cancel` | 安全取消任务 | 取消排队中或运行中的任务并终止整棵子进程树（Windows 使用 Job Object，macOS/Linux 使用 `start_new_session` + `os.killpg`）。 |

## 核心特性

- **配额与重置时间感知路由**：自动判断 5 小时或 7 天窗口是否临近重置且存在富余配额（`use_it_or_lose_it`）、充裕、适中或即将耗尽，帮助主力 Agent 自动决定该用 `gpt-6.2-astra`（`xhigh`/`high`）还是保守省着用。
- **彻底规避 MCP 3 分钟超时与高频轮询**：深度审计或大 Diff 审查传入 `background: true` 立即返回 `jobId`，支持 `codex_job_status(wait_seconds=120, include_results=true)` 单次合并等待多个后台任务。
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
| `plugin.json` 与 `mcp_config.json` | **Antigravity 独占** | 使用 Antigravity 插件清单与 `${PLUGIN_ROOT}` 变量（自动挂载为 `codex-bridge_codex-bridge`）。其他客户端请直接配置 `server/codex_mcp_server.py` 的绝对路径。 |
| `agents/codex_worker.md` | **Antigravity 独占** | 使用 Antigravity 子代理 frontmatter 规范（`subagent: true`、`call_mcp_tool`、`view_file` 等）。 |
| `RefreshMcpServers` 热重载接口（见 `AGENTS.md`） | **Antigravity 独占** | 仅用于在运行中的 Antigravity IDE 内单独热重载本 MCP 服务。 |

---

## 前置条件

1. 已安装并登录 **OpenAI Codex CLI**：
   ```bash
   codex --version
   codex login status
   ```
2. 系统 `PATH` 中包含 **Python 3.10+**（纯标准库实现，无需安装第三方包）。

---

## 安装与配置

请根据你使用的客户端选择对应的接入步骤：

### 1. Antigravity（开箱即用一体化插件）

Antigravity 会把 **MCP 服务、Skill（`codex-delegate`）、Rule（`rules/AGENTS.md`）以及子代理（`codex_worker`）** 作为一个完整插件自动全部加载。

- **方式 A — 直接克隆到 Antigravity 插件目录**（最简单）：
  - **macOS / Linux / PowerShell**：
    ```bash
    git clone https://github.com/longpi233/codex-bridge.git ~/.gemini/config/plugins/codex-bridge
    ```
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

### 2. Claude Code（配置 MCP + 安装 Skill 与 Rule）

> **注意**：不要直接复用 `mcp_config.json`（里面的 `${PLUGIN_ROOT}` 仅 Antigravity 识别），请直接指向 `server/codex_mcp_server.py` 的绝对路径。

1. **克隆仓库**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **注册 MCP 服务**：
   ```bash
   claude mcp add codex-bridge -- python -u /path/to/codex-bridge/server/codex_mcp_server.py
   ```
   *（Windows 下建议使用正斜杠路径，如 `C:/path/to/codex-bridge/server/codex_mcp_server.py`；如需全局生效，可在 `--` 前加上 `-s user`。）*

3. **安装 `codex-delegate` Skill**（可选但强烈建议：教会 Claude 先查配额、合理选模型，并在长任务时开启 `background: true`）：
   - **全局安装（所有项目可用）**：将 `skills/codex-delegate` 复制或链接到 `~/.claude/skills/codex-delegate`
     ```bash
     # macOS / Linux
     ln -s /path/to/codex-bridge/skills/codex-delegate ~/.claude/skills/codex-delegate

     # Windows（cmd 目录联接）
     mklink /J "%USERPROFILE%\.claude\skills\codex-delegate" "C:\path\to\codex-bridge\skills\codex-delegate"
     ```
   - **单项目安装**：复制到 `<你的项目>/.claude/skills/codex-delegate`。

4. **添加 Rule（可选）**：
   将 [`rules/AGENTS.md`](./rules/AGENTS.md) 中的简短规范追加到 `~/.claude/CLAUDE.md`（或项目的 `CLAUDE.md`）。

---

### 3. Cursor、Windsurf、WorkBuddy 及其他 MCP 客户端（配置 MCP + 安装 Skill 与 Rule）

> 同样**不要**直接复制包含 `${PLUGIN_ROOT}` 的 `mcp_config.json`，请填写 `server/codex_mcp_server.py` 的绝对路径（GUI 客户端如果与终端 `PATH` 不一致，建议直接填写 `python` 可执行文件的绝对路径）。

1. **克隆仓库**：
   ```bash
   git clone https://github.com/longpi233/codex-bridge.git /path/to/codex-bridge
   ```

2. **在客户端的 MCP 配置文件中添加 `codex-bridge`**（例如 `~/.cursor/mcp.json`、`.cursor/mcp.json`、`~/.workbuddy/mcp.json` 或 Windsurf 的 `mcp_config.json`）：

   ```json
   {
     "mcpServers": {
       "codex_bridge": {
         "command": "python",
         "args": [
           "-u",
           "/path/to/codex-bridge/server/codex_mcp_server.py"
         ]
       }
     }
   }
   ```
   - **Windows 提示**：路径建议使用正斜杠如 `"C:/path/to/codex-bridge/server/codex_mcp_server.py"`；若 GUI 子进程找不到 `python`，请把 `"command"` 写为本机 `python.exe` 的完整路径。
   - **针对短超时宿主（30–60s，如 WorkBuddy / DSH）**：建议在宿主 MCP 配置中调大单次工具调用超时（如 `timeout` / `toolCallTimeoutMs`），或将 `codex_job_status` 的 `wait_seconds` 控制在 `20`–`45` 秒。另请注意：`jobId` 仅在当前服务端进程生命周期内有效，而 `sessionId`（`background: true` 默认持久化）由 Codex CLI 落盘保存，重启后仍可续接。
   - **工具名提示**：像 WorkBuddy 等客户端会以 `mcp__codex_bridge__<tool>` 暴露工具名，使用下划线 key `codex_bridge` 可避免连字符被规范化替换。

3. **安装 `codex-delegate` Skill 与 Rule**（推荐）：
   - **安装 Skill**：将 `skills/codex-delegate/` 复制或软链接到对应客户端的技能目录：
     - 通用跨 Agent 规范路径（Cursor / Pi / Codex 等）：`.agents/skills/codex-delegate` 或 `~/.agents/skills/codex-delegate`
     - Cursor / WorkBuddy 路径：`.cursor/skills/codex-delegate`、`~/.workbuddy/skills/codex-delegate` 或 `.codebuddy/skills/codex-delegate`
   - **安装 Rule**：将 [`rules/AGENTS.md`](./rules/AGENTS.md) 合并到项目根目录的 `AGENTS.md`（或客户端规则目录，如 `.cursor/rules/`、`.codebuddy/rules/`）。

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

## 运行测试

运行离线单元测试、并发/取消测试与 CLI 参数测试（不消耗任何模型配额）：

```bash
python tests/test_codex_bridge.py
```

运行包含真实 Codex CLI / `app-server` 的冒烟测试（使用轻量 `gpt-6-luna` `low`，消耗极少量配额）：

```bash
python tests/test_codex_bridge.py --live
```

## 目录结构

```text
codex-bridge/
├── plugin.json                        # Antigravity 插件清单
├── mcp_config.json                    # Antigravity MCP 配置（使用 ${PLUGIN_ROOT}）
├── AGENTS.md                          # 供修改本仓库代码的 AI Agent 阅读的指南
├── README.md                          # 项目说明与配置文档（English）
├── README_CN.md                       # 项目说明与配置文档（简体中文）
├── LICENSE                            # MIT 开源协议
├── .gitignore
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
