# Codex Delegation Agent Playbook

Quick reference of concrete MCP tool call arguments for `codex-bridge`.

> **Antigravity-only note**: Wrap these arguments in `call_mcp_tool` with `"ServerName": "codex-bridge_codex-bridge"` and `"ToolName": "<tool>"`. In Claude Code, Cursor, or other MCP clients, invoke `<tool>` directly with the JSON `Arguments` below.

## 1. Sync Quota First

Tool: `codex_quota_status`

```json
{}
```

Check `recommendation.allowDelegation`, `recommendation.tier`, `recommendation.recommendedModel`, and `recommendation.recommendedReasoningEffort` before choosing a pattern below.

## 2. Pattern A: Fast Pure-Text Q&A (Sync, No File Inspection)

Use synchronous mode **only** for tiny, self-contained questions that do not inspect workspace files (`gpt-6.2-sol` with `low`). Omit `timeout_seconds` (server defaults to `900s`; never pass `< 180s`).

Tool: `codex_exec`

```json
{
  "prompt": "Compare pros/cons of token-bucket vs sliding-window rate limiting in 5 bullets.",
  "model": "gpt-6.2-sol",
  "reasoning_effort": "low",
  "sandbox": "read-only"
}
```

## 3. Pattern B: Code Inspection / Deep Analysis (`background: true` — Recommended Default)

Use `background: true` whenever Codex reads workspace files, runs shell commands, or uses `medium`/`high`/`xhigh`/`max`/`ultra` reasoning to stay safely below MCP host deadlines (e.g. Antigravity's 3-minute limit). Omit `timeout_seconds` (defaults to `900s` for `low`/`medium`, `1800s` for `high`+), or pass `0` for no hard limit when managing duration yourself.

1. Launch 1 or more parallel batches immediately (use `request_id` to make retries idempotent; `background: true` jobs default to `ephemeral: false` so they are always resumable):

Tool: `codex_exec`

```json
{
  "prompt": "Audit batch 1 (files A, B, C) for race conditions. Read all three files in one single python/rg command before analyzing.",
  "model": "gpt-6.2-astra",
  "reasoning_effort": "xhigh",
  "cwd": "/path/to/repo",
  "sandbox": "read-only",
  "background": true,
  "request_id": "audit-batch-1-v1"
}
```

2. Poll efficiently (`wait_seconds: 90`–`120` for `high`/`xhigh`/`astra`; `30`–`45` for `low`/`medium`):
   - **Single job**:
     ```json
     {
       "job_id": "<jobId>",
       "wait_seconds": 120
     }
     ```
   - **Multiple jobs (2+)**: **Omit `job_id`** to wait on all active jobs in a single call instead of alternating polls:
     ```json
     {
       "wait_seconds": 120,
       "include_results": true
     }
     ```

3. Self-directed pause & harvest (if a job runs too long or `idleSeconds` climbs):
   - Cancel cleanly: `codex_job_cancel({"job_id": "<jobId>"})` — inspect `agentMessages` & `activityLog` in the returned payload (no log-file hunting needed).
   - Harvest a structured wrap-up via `session_id`:
     ```json
     {
       "session_id": "<sessionId>",
       "model": "gpt-6.2-astra",
       "reasoning_effort": "low",
       "cwd": "/path/to/repo",
       "sandbox": "read-only",
       "background": true,
       "prompt": "Do not run any new shell commands or searches. Output all verified findings so far in the requested format."
     }
     ```

## 4. Pattern C: Multi-Turn Review -> Fix -> Re-Verify (`session_id`)

Reuse the Codex thread so Codex keeps prior context and achieves high prompt-cache hit rates:

1. **Turn 1**: Pass `"ephemeral": false` in sync `codex_exec` (already default when `"background": true`). Save `sessionId` from the result.
2. **Turn 2+**: Pass `"session_id": "<sessionId>"` (and the same `cwd` / `sandbox`). Avoid changing a `workspace-write` session to `read-only` on resume (rejected by server). Call `codex_job_status` with `{}` to list tracked `activeSessions` if you need to recover a `sessionId`.

## 5. Pattern D: Git Diff Review (`codex_review`)

- **Uncommitted changes**: `{"cwd": "<repo>", "model": "gpt-6.2-sol", "reasoning_effort": "medium", "uncommitted": true, "background": true}`
- **Branch diff**: `{"cwd": "<repo>", "base": "main", "background": true}`
- **With custom focus**: `{"cwd": "<repo>", "uncommitted": true, "focus": "Focus on SQL injection and transaction rollback paths.", "background": true}` (automatically runs via `focused-readonly-exec` and checks `workspaceChangedDuringReview`).
- **With Codex config profile or screenshot**: pass `"profile": "<name>"` to `codex_exec`/`codex_review`, or `"images": ["D:/path/to/screenshot.png"]` to `codex_exec`.

## 6. Windows Prompt Tip

To avoid per-file PowerShell `$PROFILE` startup delays on Windows, always instruct Codex in your prompt when inspecting multiple files:
> *"Read the target files together in a single command (e.g. one `python` or `rg` invocation) rather than spawning separate shell calls per file."*
