# Codex GPT Bridge

The `codex-bridge` MCP server exposes `codex_quota_status`, `codex_list_models`, `codex_exec`, `codex_review`, `codex_job_status`, and `codex_job_cancel` to call local OpenAI Codex CLI GPT models (such as `gpt-6.2-sol` and `gpt-6.2-astra`).

- Before delegating heavy verification or subtasks to Codex, check `codex_quota_status` to sync live 5-hour/7-day quota and reset times, and route model/reasoning effort accordingly.
- Prefer `sandbox: "read-only"` (or `codex_review`) when using Codex as a verifier, and use `background: true` + `codex_job_status` for tasks that may take longer than 2 minutes (helpful for MCP clients with strict per-call deadlines, such as Antigravity's 3-minute limit).
- **Antigravity note**: Antigravity mounts this server under `ServerName: "codex-bridge_codex-bridge"` and also provides the `codex_worker` subagent and `codex-delegate` skill.
