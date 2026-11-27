# Codex GPT Bridge

The `codex-bridge` MCP server exposes `codex_quota_status`, `codex_list_models`, `codex_exec`, `codex_review`, `codex_job_status`, and `codex_job_cancel` to call local OpenAI Codex CLI GPT models (such as `gpt-6.2-sol` and `gpt-6.2-astra`).

- Before delegating heavy verification or subtasks to Codex, check `codex_quota_status` to sync live 5-hour/7-day quota and reset times, and route model/reasoning effort accordingly.
- Prefer `sandbox: "read-only"` (or `codex_review`), default to `background: true` for file inspection/reviews, and omit `timeout_seconds` (defaults `900s`/`1800s`, `0` = no limit; never pass `30`–`120`).
- Poll efficiently: keep `wait_seconds` safely below your MCP host's call timeout (`~20` on 30s hosts, `30`–`45` on 60s hosts or `low`/`medium`, `90`–`120` for `high`/`xhigh`/`max`/`gpt-6.2-astra` on 180s+ hosts). Omit `job_id` with `include_results: true` when waiting on multiple jobs; for resumable `codex_exec` jobs (`resumable: true` with `sessionId`, unlike ephemeral `codex_review`), you can cancel + resume `session_id` (`low` effort) for early wrap-up.
- **Antigravity note**: Antigravity mounts this server under `ServerName: "codex-bridge_codex-bridge"` and also provides the `codex_worker` subagent and `codex-delegate` skill.
