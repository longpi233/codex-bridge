# Codex GPT Bridge

The `codex-bridge` MCP server exposes `codex_quota_status`, `codex_list_models`, `codex_exec`, `codex_review`, `codex_job_status`, and `codex_job_cancel` to call local OpenAI Codex CLI GPT models (such as `gpt-6.2-sol` and `gpt-6.2-astra`).

- Before delegating heavy verification or subtasks to Codex, check `codex_quota_status` to sync live 5-hour/7-day quota and reset times, and route model/reasoning effort accordingly.
- Prefer `sandbox: "read-only"` (or `codex_review`), default to `background: true` + `codex_job_status(wait_seconds=30)` for file inspection/reviews (avoids 3-minute MCP client deadlines), and omit `timeout_seconds` unless raising it for huge audits (never pass small values like `30`–`120`).
- **Antigravity note**: Antigravity mounts this server under `ServerName: "codex-bridge_codex-bridge"` and also provides the `codex_worker` subagent and `codex-delegate` skill.
