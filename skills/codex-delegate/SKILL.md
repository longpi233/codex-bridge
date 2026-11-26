---
name: codex-delegate
description: >-
  Delegate verification, code review, or bounded subtasks to OpenAI Codex CLI
  GPT models (such as gpt-6.2-sol and gpt-6.2-astra) via the codex-bridge
  MCP server, with live account quota and reset-time-aware task routing.
---

# Codex GPT Delegation & Verification

Use this skill whenever you want a **second opinion from a GPT model**, need **cross-model verification** of code/plans/diffs, or want to **offload a bounded subtask** to Codex CLI.

> **Antigravity-only note**: Antigravity namespaces this plugin's MCP server as `ServerName: "codex-bridge_codex-bridge"` (called via `call_mcp_tool`) and provides the `codex_worker` subagent. Other MCP clients (Claude Code, Cursor, etc.) invoke the bare tool names directly on the `codex-bridge` server.

## 1. Always Check Quota & Reset Time First

Before dispatching a non-trivial Codex task, call `codex_quota_status`:

- **5-hour primary window (`primary5hWindow`)** and **7-day secondary window (`secondary7dWindow`)** report `usedPercent`, `remainingPercent`, `resetsAtLocal`, and `minutesUntilReset` (single-window plans without a 5h limit, such as weekly-only Pro plans, automatically normalize into `secondary7dWindow`).
- **`pacingMetrics`** computes `surplusRatio = remainingPercent / remainingWindowTimePercent`. A ratio `> 1.0` means your remaining quota outpaces the remaining time before reset.
- Use `recommendation` (`tier`, `strategy`, `suggestedUseCases`, `avoidUseCases`) to decide **whether** and **how** to delegate:

| Tier | Condition | Recommended Model & Effort | Strategy & Diverse Use Cases |
| :--- | :--- | :--- | :--- |
| `unlimited` | `credits.unlimited == true` | `gpt-6.2-astra` (`high`) or `gpt-6.2-sol` (`medium`) | **Free delegation**: deep architecture/security audits, pre-merge reviews, parallel subtasks without rolling window caps. |
| `use_it_or_lose_it` | Weekly reset <=24h with surplus >=1.5x (or <=6h & >=8%), OR 5h reset <=60m with >=25% left | `gpt-6.2-astra` (`xhigh` / `high`) or parallel `gpt-6.2-sol` (`high`) | **Maximize burn before reset**: deep architecture/security audits, parallel background jobs/workers across modules, test-suite generation, refactoring proposals. |
| `abundant` | >= 50% remaining on active window(s) | `gpt-6.2-astra` (`high`) or `gpt-6.2-sol` (`medium`/`high`) | **Free delegation**: cross-model design verification, pre-merge `codex_review`, bounded implementation subtasks. |
| `moderate_surplus` | 20%–49% remaining, but 7d surplus >=1.2x or 5h resets <=90m | `gpt-6.2-sol` (`high`) or `gpt-6.2-astra` (`medium`) | **Selective deep or standard**: focused `codex_review` on uncommitted diffs, targeted `astra` audit on high-risk paths (auth/concurrency/data). |
| `moderate` | 20%–49% remaining, normal pacing | `gpt-6.2-sol` (`medium`) | **Focused verification**: single-module diff review, concrete bug/API contract checks. |
| `api_payg` | API-key pay-as-you-go account (no 5h/7d windows) | `gpt-6.2-sol` (`medium`) or `gpt-6.2-astra` (`high`) | **Cost-aware delegation**: standard reviews with `gpt-6.2-sol`; reserve `gpt-6.2-astra` for high-risk or complex tasks. |
| `conserve_5h_short_wait` | 5h <20% & resets <=60m, while 7d >=25% | `gpt-6.2-sol` (`low`) now | **Defer heavy work**: run only tiny sanity checks now and queue deep `astra` reviews after the 5h reset. |
| `conserve` | < 20% remaining with long wait | `gpt-6.2-sol` (`low`) | **High-ROI only**: concise read-only checks on critical diffs or specific error traces. |
| `exhausted` | < 3% remaining or blocked | None | **Wait for reset**: report `resetsAtLocal` to the user and verify locally (or ask if they want to use a reset credit). |
| `unknown` | Live rate-limit windows unavailable | `gpt-6.2-sol` (`low`) | Proceed conservatively with small checks until quota status is confirmed. |

If you are unsure which model slugs are currently enabled on the user's account, call `codex_list_models`.

## 2. Choose the Right Tool

1. **Git diff / repository review (`codex_review`)**:
   - Runs strictly in `read-only` mode against `cwd` (supports optional `profile`).
   - Specify one target: `uncommitted: true` (default when `base`/`commit` omitted), `base: "main"`, or `commit: "<sha>"`. Adding `focus` automatically routes through a read-only `codex exec` scoped to that diff.
2. **General verification or bounded subtask (`codex_exec`)**:
   - Keep `sandbox: "read-only"` (default) for verification, audits, design critique, or Q&A.
   - Use `sandbox: "workspace-write"` **only** when explicitly delegating file edits to Codex, and review the resulting diff afterward.
   - Pass `cwd` when Codex needs to inspect workspace files (validated upfront to exist).
   - Optional **`profile`** (`-p`) reuses a named config profile in `$CODEX_HOME`, and **`images`** (`-i`) attaches local screenshots/images for multimodal visual verification.
   - **Multi-turn context continuity (`session_id`)**: For one-off checks keep `ephemeral: true` (default). When you expect follow-up turns on the same task (e.g. initial review -> Antigravity fixes -> Codex re-verifies), pass `ephemeral: false` on the first `codex_exec` call to get a `sessionId`, then pass `session_id: "<sessionId>"` on subsequent calls to resume with full prior context and prompt caching (call `codex_job_status` with no `job_id` to inspect tracked `activeSessions`).
3. **Parallel & Background Execution (`background: true`)**:
   - **Avoid MCP client call timeouts**: Many MCP hosts enforce strict per-call deadlines (e.g. Antigravity's 3-minute / `180s` limit). For `gpt-6.2-astra`, `high`/`xhigh` reasoning, multi-file audits, or large reviews, **always pass `background: true`** (plus an optional `request_id` for safe retries) to `codex_exec` or `codex_review`, then poll `codex_job_status(job_id=..., wait_seconds=25)` until completion (or cancel with `codex_job_cancel`).
   - **Antigravity-only (`codex_worker` subagent)**: In Antigravity, you can invoke `codex_worker` via `invoke_subagent` to check quota, manage background Codex jobs, and wake you automatically with a structured summary.

## 3. Verification & Performance Best Practices

- **Split large multi-file audits into bounded batches**: Avoid sending 20+ files to a single `codex_exec` call. Split into parallel batches of ~5–10 files via `background: true` jobs (or parallel `codex_worker` subagents in Antigravity).
- **Windows tip — minimize sequential shell calls**: On Windows, each shell invocation inside Codex can incur PowerShell `$PROFILE` startup overhead. When asking Codex to inspect multiple files on Windows, instruct it to batch reads/searches in a single command (e.g. `rg` or one `python` script) rather than reading files one-by-one.
- **Give concrete acceptance criteria**: Supply exact file paths, reproduction steps, or diff scope, and verify any reported findings before reporting them as fixed.
- **Concrete call payloads**: See [Agent Playbook](./references/playbook.md) for copy-ready JSON argument examples (`background: true`, `session_id`, `codex_review`, and polling).
