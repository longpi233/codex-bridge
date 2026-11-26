# Codex Delegation Agent Playbook

Quick reference of concrete MCP tool call arguments for `codex-bridge`.

> **Antigravity-only note**: Wrap these arguments in `call_mcp_tool` with `"ServerName": "codex-bridge_codex-bridge"` and `"ToolName": "<tool>"`. In Claude Code, Cursor, or other MCP clients, invoke `<tool>` directly with the JSON `Arguments` below.

## 1. Sync Quota First

Tool: `codex_quota_status`

```json
{}
```

Check `recommendation.allowDelegation`, `recommendation.tier`, `recommendation.recommendedModel`, and `recommendation.recommendedReasoningEffort` before choosing a pattern below.

## 2. Pattern A: Fast Read-Only Verification (Sync, < 2 min)

Use only for small, bounded questions (`gpt-6.2-sol` with `low`/`medium`).

Tool: `codex_exec`

```json
{
  "prompt": "Inspect src/auth.py lines 40-120 for token expiry edge cases. Read in a single command.",
  "model": "gpt-6.2-sol",
  "reasoning_effort": "medium",
  "cwd": "/path/to/repo",
  "sandbox": "read-only"
}
```

## 3. Pattern B: Deep / Multi-Batch Analysis (`background: true`)

Required for `gpt-6.2-astra`, `high`/`xhigh`/`max`/`ultra` reasoning, or multi-file audits to stay under strict MCP call deadlines (e.g. Antigravity's 3-minute ceiling).

1. Launch 1 or more parallel batches immediately (use `request_id` to make retries idempotent):

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

2. Poll with `wait_seconds: 25` (safe inside 180s limit):

Tool: `codex_job_status`

```json
{
  "job_id": "<jobId>",
  "wait_seconds": 25
}
```

3. Cancel if no longer needed:

Tool: `codex_job_cancel`

```json
{
  "job_id": "<jobId>"
}
```

## 4. Pattern C: Multi-Turn Review -> Fix -> Re-Verify (`session_id`)

Reuse the Codex thread so Codex keeps prior context and achieves high prompt-cache hit rates:

1. **Turn 1**: Pass `"ephemeral": false` in `codex_exec` (alongside `"background": true` if heavy). Save `sessionId` from the result.
2. **Turn 2+**: Pass `"session_id": "<sessionId>"` (and the same `cwd` / `sandbox`). Avoid changing a `workspace-write` session to `read-only` on resume (rejected by server). Call `codex_job_status` with `{}` to list tracked `activeSessions` if you need to recover a `sessionId`.

## 5. Pattern D: Git Diff Review (`codex_review`)

- **Uncommitted changes**: `{"cwd": "<repo>", "model": "gpt-6.2-sol", "reasoning_effort": "medium", "uncommitted": true, "background": true}`
- **Branch diff**: `{"cwd": "<repo>", "base": "main", "background": true}`
- **With custom focus**: `{"cwd": "<repo>", "uncommitted": true, "focus": "Focus on SQL injection and transaction rollback paths.", "background": true}` (automatically runs via `focused-readonly-exec` and checks `workspaceChangedDuringReview`).
- **With Codex config profile or screenshot**: pass `"profile": "<name>"` to `codex_exec`/`codex_review`, or `"images": ["D:/path/to/screenshot.png"]` to `codex_exec`.

## 6. Windows Prompt Tip

To avoid per-file PowerShell `$PROFILE` startup delays on Windows, always instruct Codex in your prompt when inspecting multiple files:
> *"Read the target files together in a single command (e.g. one `python` or `rg` invocation) rather than spawning separate shell calls per file."*
