import argparse
import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PATH = os.path.join(REPO_ROOT, "server", "codex_mcp_server.py")

spec = importlib.util.spec_from_file_location("codex_mcp_server", SERVER_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def _make_fake_codex(tmpdir: str, name: str, script_body: str) -> str:
    py_path = os.path.join(tmpdir, f"{name}.py")
    with open(py_path, "w", encoding="utf-8") as f:
        f.write(script_body)
    if os.name == "nt":
        cmd_path = os.path.join(tmpdir, f"{name}.cmd")
        with open(cmd_path, "w", encoding="utf-8") as f:
            f.write(f'@echo off\r\n"{sys.executable}" "{py_path}" %*\r\n')
        return cmd_path
    sh_path = os.path.join(tmpdir, f"{name}.sh")
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{py_path}" "$@"\n')
    os.chmod(sh_path, 0o755)
    return sh_path


def test_unit_fixes():
    # 1. UTF-8 and locale/GBK decoding
    utf8_bytes = "Error: 找不到路径 (os error 3)".encode("utf-8")
    assert mod._decode_bytes(utf8_bytes) == "Error: 找不到路径 (os error 3)"

    gbk_bytes = "Error: 系统找不到指定的路径。 (os error 3)".encode("gbk")
    decoded = mod._decode_bytes(gbk_bytes)
    assert isinstance(decoded, str) and len(decoded) > 0
    is_gbk_host = False
    if os.name == "nt":
        try:
            import ctypes
            is_gbk_host = ctypes.windll.kernel32.GetACP() in (936, 54936)
        except Exception:
            pass
    else:
        import locale
        pref = (locale.getpreferredencoding(False) or "").lower()
        is_gbk_host = any(k in pref for k in ("gbk", "936", "gb18030"))
    if is_gbk_host:
        assert "系统找不到指定的路径" in decoded, f"Bad decode: {decoded!r}"
        assert "\ufffd" not in decoded

    # 2. Missing cwd validation
    missing_dir = os.path.join(tempfile.gettempdir(), "definitely_does_not_exist_99999")
    try:
        mod.tool_exec({"prompt": "hi", "cwd": missing_dir})
        raise AssertionError("Expected ValueError for nonexistent cwd")
    except ValueError as exc:
        assert "does not exist" in str(exc)

    # 3. Strict boolean validation
    try:
        mod.tool_exec({"prompt": "hi", "background": "false"})
        raise AssertionError("Expected ValueError for string 'false'")
    except ValueError as exc:
        assert "boolean" in str(exc)

    # 4. Missing rate-limit windows & Pro/unlimited/API-key normalization
    rec = mod._compute_recommendation(None, None, None)
    assert rec["tier"] == "unknown", rec

    rec_blocked = mod._compute_recommendation(False, None, None)
    assert rec_blocked["tier"] == "exhausted" and rec_blocked["allowDelegation"] is False, rec_blocked

    rec_unlim = mod._compute_recommendation(True, None, None, credits={"unlimited": True})
    assert rec_unlim["tier"] == "unlimited" and rec_unlim["allowDelegation"] is True, rec_unlim

    rec_api = mod._compute_recommendation(True, None, None, account={"type": "apiKey"})
    assert rec_api["tier"] == "api_payg" and rec_api["allowDelegation"] is True, rec_api

    # Pro plan reporting only a 7d weekly window inside `primary` (no 5h limit)
    now_ts = time.time()
    p_norm, s_norm = mod._classify_windows(
        {"usedPercent": 60, "windowDurationMins": 10080, "resetsAt": now_ts + 3 * 3600},
        None,
    )
    assert p_norm is None and s_norm is not None and s_norm["windowDurationMins"] == 10080, (p_norm, s_norm)
    rec_pro_burn = mod._compute_recommendation(True, p_norm, s_norm)
    assert rec_pro_burn["tier"] == "use_it_or_lose_it", rec_pro_burn

    _, s_abund = mod._classify_windows(
        {"usedPercent": 20, "windowDurationMins": 10080, "resetsAt": now_ts + 5 * 86400},
        None,
    )
    rec_pro_abund = mod._compute_recommendation(True, None, s_abund)
    assert rec_pro_abund["tier"] == "abundant", rec_pro_abund
    assert "no 5h window limit" in rec_pro_abund["guidance"]
    assert "None" not in rec_pro_abund["guidance"]

    _, s_mod = mod._classify_windows(
        {"usedPercent": 70, "windowDurationMins": 10080, "resetsAt": now_ts + 30 * 3600},
        None,
    )
    rec_pro_mod = mod._compute_recommendation(True, None, s_mod)
    assert rec_pro_mod["tier"] == "moderate_surplus", rec_pro_mod
    assert "None" not in rec_pro_mod["guidance"]

    # tool_quota_status live path succeeds without fallback when credits.unlimited is True
    orig_call_batch = mod.APP_SERVER.call_batch
    try:
        mod.APP_SERVER.call_batch = lambda reqs, timeout=15.0: [
            {"result": {"account": {"type": "chatgpt", "planType": "pro"}}},
            {"result": {"ordinaryUsageAllowed": True, "rateLimits": {"primary": None, "secondary": None, "credits": {"hasCredits": True, "unlimited": True}}}},
        ]
        q_unlim = mod.tool_quota_status({})
        assert q_unlim["source"] == "codex-app-server-live"
        assert q_unlim["recommendation"]["tier"] == "unlimited", q_unlim
    finally:
        mod.APP_SERVER.call_batch = orig_call_batch

    # 5. Session binding mismatch check on resume
    with mod.SESSIONS_LOCK:
        mod.SESSION_BINDINGS["sess-test-1"] = {"cwd": os.path.abspath("."), "sandbox": "workspace-write"}
    try:
        mod.tool_exec({"prompt": "hi", "session_id": "sess-test-1", "sandbox": "read-only"})
        raise AssertionError("Expected refusal for read-only resume on workspace-write session")
    except ValueError as exc:
        assert "workspace-write" in str(exc)

    # 6. Review mutually exclusive target check & empty target check
    try:
        mod.tool_review({"cwd": os.path.dirname(SERVER_PATH), "uncommitted": True, "base": "main"})
        raise AssertionError("Expected ValueError for uncommitted=True + base")
    except ValueError as exc:
        assert "cannot be combined" in str(exc)

    try:
        mod.tool_review({"cwd": os.path.dirname(SERVER_PATH), "uncommitted": False})
        raise AssertionError("Expected ValueError for uncommitted=False with no base/commit/focus")
    except ValueError as exc:
        assert "Must specify at least one" in str(exc)

    # 7. _WinJobObject.close() idempotent & safe when called concurrently
    job_obj = mod._WinJobObject()
    close_errors = []

    def _closer():
        try:
            job_obj.close()
        except Exception as exc:
            close_errors.append(exc)

    threads = [threading.Thread(target=_closer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    job_obj.close()
    assert not close_errors, f"Concurrent close errors: {close_errors}"
    assert job_obj.handle is None

    # 8. _git_fingerprint disables hooks/fsmonitor and detects unstaged, staged, and untracked changes
    orig_subproc_run = mod.subprocess.run
    try:
        with tempfile.TemporaryDirectory() as fp_dir:
            untracked_file = os.path.join(fp_dir, "untracked.txt")
            with open(untracked_file, "wb") as uf:
                uf.write(b"v1")
            diff_payload = [b"diff --git a/a.py b/a.py\n-x = 1\n+x = 2\n"]
            cached_payload = [b""]
            status_payload = [b" M a.py\x00?? untracked.txt\x00"]
            fail_diff = [False]

            def fake_git_run(cmd, **kwargs):
                assert "-c" in cmd and "core.fsmonitor=false" in cmd and "core.hooksPath=" in cmd, cmd

                class Res:
                    def __init__(self, returncode, stdout):
                        self.returncode = returncode
                        self.stdout = stdout

                if "rev-parse" in cmd:
                    return Res(0, b"deadbeef\n")
                if "status" in cmd:
                    return Res(0, status_payload[0])
                if "--cached" in cmd:
                    return Res(0, cached_payload[0])
                if "diff" in cmd:
                    return Res(1 if fail_diff[0] else 0, diff_payload[0])
                raise AssertionError(f"Unexpected command: {cmd}")

            mod.subprocess.run = fake_git_run
            fp1 = mod._git_fingerprint(fp_dir)
            diff_payload[0] = b"diff --git a/a.py b/a.py\n-x = 1\n+x = 3\n"
            fp2 = mod._git_fingerprint(fp_dir)
            assert fp1 is not None and fp2 is not None and fp1 != fp2, (fp1, fp2)

            cached_payload[0] = b"diff --git a/b.py b/b.py\n+staged = 1\n"
            fp3 = mod._git_fingerprint(fp_dir)
            assert fp3 is not None and fp3 != fp2

            with open(untracked_file, "wb") as uf:
                uf.write(b"v2-modified")
            fp4 = mod._git_fingerprint(fp_dir)
            assert fp4 is not None and fp4 != fp3

            fail_diff[0] = True
            assert mod._git_fingerprint(fp_dir) is None
    finally:
        mod.subprocess.run = orig_subproc_run

    # 9. _AppServerClient real _read_stdout EOF does not clear a restarted process's _pending
    orig_popen = mod.subprocess.Popen
    orig_resolve = mod._resolve_codex_command
    try:
        eof_gate = threading.Event()
        init_sent = threading.Event()

        class FakeStdin:
            def write(self, data):
                if b'"initialize"' in data:
                    init_sent.set()

            def flush(self):
                pass

            def close(self):
                pass

        class FakeStdout:
            def __init__(self):
                self._step = 0

            def readline(self):
                if self._step == 0:
                    self._step += 1
                    init_sent.wait(timeout=2.0)
                    return b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n'
                eof_gate.wait(timeout=2.0)
                return b""

        class FakeStderr:
            def readline(self):
                return b""

        class FakeAppProc:
            def __init__(self, *args, **kwargs):
                self.stdin = FakeStdin()
                self.stdout = FakeStdout()
                self.stderr = FakeStderr()
                self._handle = None
                self._dead = False

            def poll(self):
                return 0 if self._dead else None

            def terminate(self):
                self._dead = True
                eof_gate.set()

            def kill(self):
                self._dead = True
                eof_gate.set()

            def wait(self, timeout=None):
                self._dead = True
                return 0

        mod._resolve_codex_command = lambda: ("fake-codex", {})
        mod.subprocess.Popen = FakeAppProc
        client = mod._AppServerClient()
        with client._lock:
            client._start_unlocked(timeout=5.0)
        new_ev = threading.Event()
        new_box = []
        with client._pending_lock:
            client._proc = object()  # simulate restarted process
            client._pending[999] = (new_ev, new_box)
        eof_gate.set()
        time.sleep(0.15)
        assert not new_ev.is_set() and 999 in client._pending and new_box == []
    finally:
        mod.subprocess.Popen = orig_popen
        mod._resolve_codex_command = orig_resolve

    # 10. _validate_images and _validate_profile
    try:
        mod._validate_images("not-a-list")
        raise AssertionError("Expected ValueError for non-list images")
    except ValueError as exc:
        assert "array" in str(exc)

    missing_img = os.path.join(tempfile.gettempdir(), "definitely_missing_image_99999.png")
    try:
        mod._validate_images([missing_img])
        raise AssertionError("Expected ValueError for missing image")
    except ValueError as exc:
        assert "does not exist" in str(exc)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_img = tf.name
    try:
        assert mod._validate_images([tmp_img]) == [os.path.abspath(tmp_img)]
    finally:
        try:
            os.remove(tmp_img)
        except OSError:
            pass

    try:
        mod._validate_profile("   ")
        raise AssertionError("Expected ValueError for empty profile")
    except ValueError as exc:
        assert "non-empty" in str(exc)

    try:
        mod._validate_profile("-bad")
        raise AssertionError("Expected ValueError for leading-dash profile")
    except ValueError as exc:
        assert "must not start with" in str(exc)

    assert mod._validate_profile("  fast-sol  ") == "fast-sol"

    # 11. SESSION_BINDINGS pruning & activeSessions in tool_job_status({})
    orig_max_sessions = mod.MAX_RETAINED_SESSIONS
    with mod.SESSIONS_LOCK:
        saved_bindings = dict(mod.SESSION_BINDINGS)
        saved_locks = dict(mod.SESSION_RUN_LOCKS)
    try:
        mod.MAX_RETAINED_SESSIONS = 3
        with mod.SESSIONS_LOCK:
            mod.SESSION_BINDINGS.clear()
            mod.SESSION_RUN_LOCKS.clear()
            for i in range(5):
                sid = f"prune-sess-{i}"
                mod.SESSION_BINDINGS[sid] = {
                    "cwd": REPO_ROOT,
                    "sandbox": "read-only",
                    "model": "gpt-6.2-sol",
                    "lastUsedAt": 1700000000.0 + i,
                }
                mod.SESSION_RUN_LOCKS[sid] = threading.Lock()
            mod._prune_sessions_unlocked()
            assert len(mod.SESSION_BINDINGS) == 3
            assert "prune-sess-0" not in mod.SESSION_BINDINGS
            assert "prune-sess-4" in mod.SESSION_BINDINGS
        status_all = mod.tool_job_status({})
        assert "activeSessions" in status_all
        assert [s["sessionId"] for s in status_all["activeSessions"]] == [
            "prune-sess-4",
            "prune-sess-3",
            "prune-sess-2",
        ]
    finally:
        mod.MAX_RETAINED_SESSIONS = orig_max_sessions
        with mod.SESSIONS_LOCK:
            mod.SESSION_BINDINGS.clear()
            mod.SESSION_BINDINGS.update(saved_bindings)
            mod.SESSION_RUN_LOCKS.clear()
            mod.SESSION_RUN_LOCKS.update(saved_locks)

    # 12. _terminate_process_tree POSIX killpg path test (mocked safely on any OS)
    orig_os_name = mod.os.name
    orig_killpg = getattr(mod.os, "killpg", None)
    orig_sigterm = getattr(mod.signal, "SIGTERM", 15)
    orig_sigkill = getattr(mod.signal, "SIGKILL", 9)
    try:
        killpg_calls = []

        class FakePosixProc:
            def __init__(self):
                self.pid = 42424
                self._alive = True

            def poll(self):
                return None if self._alive else 0

            def wait(self, timeout=None):
                if self._alive:
                    raise subprocess.TimeoutExpired("fake", timeout or 1.0)
                return 0

            def terminate(self):
                self._alive = False

            def kill(self):
                self._alive = False

        fake_posix_proc = FakePosixProc()

        def fake_killpg(pgid, sig):
            killpg_calls.append((pgid, sig))
            if sig == orig_sigkill:
                fake_posix_proc._alive = False

        mod.os.name = "posix"
        mod.os.killpg = fake_killpg
        mod.signal.SIGTERM = orig_sigterm
        mod.signal.SIGKILL = orig_sigkill
        mod._terminate_process_tree(fake_posix_proc, None)
        assert killpg_calls == [(42424, orig_sigterm), (42424, orig_sigkill)], killpg_calls

        # Surviving grandchild after leader has already exited still gets SIGTERM -> SIGKILL
        exited_leader = FakePosixProc()
        exited_leader._alive = False
        grandchild_alive = True
        gc_calls = []

        def fake_gc_killpg(pgid, sig):
            nonlocal grandchild_alive
            gc_calls.append((pgid, sig))
            if sig == 0 and not grandchild_alive:
                raise ProcessLookupError()
            if sig == orig_sigkill:
                grandchild_alive = False

        mod.os.killpg = fake_gc_killpg
        mod._terminate_process_tree(exited_leader, None)
        assert gc_calls[0] == (42424, orig_sigterm) and gc_calls[-1] == (42424, orig_sigkill), gc_calls

        # Already-reaped process must never signal a potentially recycled PGID
        reaped_proc = FakePosixProc()
        reaped_proc._alive = False
        reaped_proc.returncode = 0
        reaped_calls = []
        mod.os.killpg = lambda pgid, sig: reaped_calls.append((pgid, sig))
        mod._terminate_process_tree(reaped_proc, None)
        assert reaped_calls == [], reaped_calls
    finally:
        mod.os.name = orig_os_name
        if orig_killpg is None:
            if hasattr(mod.os, "killpg"):
                delattr(mod.os, "killpg")
        else:
            mod.os.killpg = orig_killpg
        if hasattr(mod.signal, "SIGTERM"):
            mod.signal.SIGTERM = orig_sigterm
        if hasattr(mod.signal, "SIGKILL"):
            mod.signal.SIGKILL = orig_sigkill

    # 13. _resolve_timeout_seconds defaults (900/1800), 0=no-limit, floors (180/300), cap (3600)
    assert mod._resolve_timeout_seconds(None, None) == 900
    assert mod._resolve_timeout_seconds(None, "medium") == 900
    assert mod._resolve_timeout_seconds(None, "high") == 1800
    assert mod._resolve_timeout_seconds(None, "xhigh") == 1800
    assert mod._resolve_timeout_seconds(0, "xhigh") == 0
    assert mod._resolve_timeout_seconds(30, "low") == 180
    assert mod._resolve_timeout_seconds(60, "xhigh") == 300
    assert mod._resolve_timeout_seconds(9999, "low") == 3600

    # 14. background: true defaults ephemeral=False (resumable), sync defaults ephemeral=True
    with tempfile.TemporaryDirectory() as bg_dir:
        fc_bg = _make_fake_codex(
            bg_dir,
            "fake_bg_ephem",
            """import json, sys
args = sys.argv[1:]
if "review" not in args:
    _ = sys.stdin.read()
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("BG_OK")
print(json.dumps({"type": "thread.started", "thread_id": "sess-bg-1"}))
""",
        )
        old_cb = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fc_bg
        try:
            sync_res = mod.tool_exec({"prompt": "sync check", "cwd": bg_dir})
            assert sync_res["resumable"] is False
            assert sync_res.get("usageUnavailable") is True and "usage" not in sync_res, sync_res

            bg_res = mod.tool_exec({"prompt": "bg check", "cwd": bg_dir, "background": True})
            assert bg_res["resumable"] is True
            assert "30-45" in bg_res.get("note", "") and "90-120" in bg_res.get("note", ""), bg_res
            done_bg = mod.tool_job_status({"job_id": bg_res["jobId"], "wait_seconds": 120})
            assert done_bg["status"] == "completed" and "toolCallsCount" in done_bg

            # Verify wait_seconds=120 works on listing too
            all_st = mod.tool_job_status({"wait_seconds": 120})
            assert "totalJobs" in all_st
        finally:
            if old_cb is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_cb

    # 15. Timeout preserves full agentMessages + activityLog + resumable hint without log hunting
    with tempfile.TemporaryDirectory() as to_dir:
        fc_to = _make_fake_codex(
            to_dir,
            "fake_to",
            """import json, sys, time
args = sys.argv[1:]
_ = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "sess-to-1"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "rg foo src/", "exit_code": 0, "aggregated_output": "src/a.py:10:foo"}}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Partial finding 1: checked src/a.py."}}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Partial finding 2: checking src/b.py next."}}), flush=True)
time.sleep(10.0)
""",
        )
        old_cb = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fc_to
        try:
            to_res = mod._run_codex_exec(
                [fc_to, "exec", "-C", to_dir, "-s", "read-only"],
                prompt="audit",
                timeout_seconds=3,
                session_meta={"cwd": to_dir, "sandbox": "read-only", "model": "gpt-6.2-astra"},
            )
            assert to_res["timedOut"] is True and to_res["exitCode"] == -1, to_res
            assert "Partial finding 1" in to_res["response"] and "Partial finding 2" in to_res["response"], to_res
            assert len(to_res.get("agentMessages", [])) == 2, to_res
            assert to_res.get("activityLog") and to_res["activityLog"][0]["command"] == "rg foo src/", to_res
            assert "sess-to-1" in to_res.get("warning", ""), to_res
        finally:
            if old_cb is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_cb

    # 16. _default_model, _filter_stderr_noise, and CODEX_BIN npm env injection
    old_def_model = os.environ.pop("CODEX_DEFAULT_MODEL", None)
    try:
        assert mod._default_model() is None
        os.environ["CODEX_DEFAULT_MODEL"] = " gpt-6.2-sol "
        assert mod._default_model() == "gpt-6.2-sol"
    finally:
        if old_def_model is None:
            os.environ.pop("CODEX_DEFAULT_MODEL", None)
        else:
            os.environ["CODEX_DEFAULT_MODEL"] = old_def_model

    filtered_err = mod._filter_stderr_noise(
        "WARNING: failed to clean up stale arg0 temp dirs: 拒绝访问。 (os error 5)\n"
        "WARNING: proceeding, even though we could not create PATH aliases: 拒绝访问。\n"
        "ERROR: real failure happened"
    )
    assert filtered_err == "ERROR: real failure happened", filtered_err

    with tempfile.TemporaryDirectory() as npm_tmp:
        pkg_root = os.path.join(npm_tmp, "node_modules", "@openai", "codex")
        fake_exe = os.path.join(
            pkg_root, "node_modules", "@openai", "codex-win32-x64", "vendor", "x86_64-pc-windows-msvc", "bin", "codex.exe"
        )
        os.makedirs(os.path.dirname(fake_exe), exist_ok=True)
        with open(fake_exe, "wb") as f:
            f.write(b"")
        old_cb = os.environ.get("CODEX_BIN")
        old_mgr = os.environ.pop("CODEX_MANAGED_BY_NPM", None)
        old_root = os.environ.pop("CODEX_MANAGED_PACKAGE_ROOT", None)
        os.environ["CODEX_BIN"] = fake_exe
        try:
            resolved_bin, resolved_env = mod._resolve_codex_command()
            assert resolved_bin == fake_exe
            assert resolved_env.get("CODEX_MANAGED_BY_NPM") == "1"
            assert resolved_env.get("CODEX_MANAGED_PACKAGE_ROOT") == os.path.abspath(pkg_root)
        finally:
            if old_cb is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_cb
            if old_mgr is not None:
                os.environ["CODEX_MANAGED_BY_NPM"] = old_mgr
            if old_root is not None:
                os.environ["CODEX_MANAGED_PACKAGE_ROOT"] = old_root

    # 17. Usage non-zero detection, host-agnostic recommendations, email masking, and optional JSONL logging
    assert mod._has_nonzero_usage(None) is False
    assert mod._has_nonzero_usage({}) is False
    assert mod._has_nonzero_usage({"input_tokens": 0, "output_tokens": 0}) is False
    assert mod._has_nonzero_usage({"input_tokens": 120, "output_tokens": 0}) is True

    rec_samples = [
        mod._compute_recommendation(False, None, None),
        mod._compute_recommendation(True, None, None, credits={"unlimited": True}),
        mod._compute_recommendation(True, None, None, account={"type": "apiKey"}),
        mod._compute_recommendation(True, None, None),
        mod._compute_recommendation(True, {"remainingPercent": 80, "minutesUntilReset": 30}, None),
        mod._compute_recommendation(True, {"remainingPercent": 70, "minutesUntilReset": 200}, {"remainingPercent": 60, "minutesUntilReset": 4000}),
        mod._compute_recommendation(True, {"remainingPercent": 40, "minutesUntilReset": 80}, {"remainingPercent": 40, "minutesUntilReset": 2000}),
        mod._compute_recommendation(True, {"remainingPercent": 35, "minutesUntilReset": 240}, {"remainingPercent": 35, "minutesUntilReset": 8000}),
        mod._compute_recommendation(True, {"remainingPercent": 10, "minutesUntilReset": 30}, {"remainingPercent": 50, "minutesUntilReset": 5000}),
        mod._compute_recommendation(True, {"remainingPercent": 10, "minutesUntilReset": 240}, {"remainingPercent": 10, "minutesUntilReset": 5000}),
    ]
    assert len({r["tier"] for r in rec_samples}) == 10, [r["tier"] for r in rec_samples]
    for rec in rec_samples:
        dumped = json.dumps(rec, ensure_ascii=False)
        for forbidden in ("Antigravity", "codex_worker", "invoke_subagent"):
            assert forbidden not in dumped, (rec["tier"], forbidden, dumped)

    old_inc_email = os.environ.pop("CODEX_BRIDGE_INCLUDE_EMAIL", None)
    try:
        masked = mod._mask_account({"type": "chatgpt", "email": "alice@example.com", "planType": "pro"})
        assert masked["email"] == "a***@example.com" and masked["planType"] == "pro", masked
        os.environ["CODEX_BRIDGE_INCLUDE_EMAIL"] = "1"
        unmasked = mod._mask_account({"type": "chatgpt", "email": "alice@example.com"})
        assert unmasked["email"] == "alice@example.com", unmasked
    finally:
        if old_inc_email is None:
            os.environ.pop("CODEX_BRIDGE_INCLUDE_EMAIL", None)
        else:
            os.environ["CODEX_BRIDGE_INCLUDE_EMAIL"] = old_inc_email

    with tempfile.TemporaryDirectory() as log_dir:
        log_file = os.path.join(log_dir, "bridge.jsonl")
        old_log_env = os.environ.pop("CODEX_BRIDGE_LOG_FILE", None)
        try:
            mod._log_event("disabled_check")
            assert not os.path.exists(log_file)
            os.environ["CODEX_BRIDGE_LOG_FILE"] = log_file
            mod._log_event("enabled_check", ok=True)
            with open(log_file, encoding="utf-8") as lf:
                logged = [json.loads(line) for line in lf.read().splitlines() if line.strip()]
            assert len(logged) == 1 and logged[0]["event"] == "enabled_check" and logged[0]["ok"] is True, logged
        finally:
            if old_log_env is None:
                os.environ.pop("CODEX_BRIDGE_LOG_FILE", None)
            else:
                os.environ["CODEX_BRIDGE_LOG_FILE"] = old_log_env

    # 18. JSON-RPC id validation, session lock pinning under pruning, and packer self-overwrite guard
    assert mod._is_valid_jsonrpc_id("abc") is True
    assert mod._is_valid_jsonrpc_id(42) is True
    assert mod._is_valid_jsonrpc_id(True) is False
    assert mod._is_valid_jsonrpc_id([1, 2]) is False
    assert mod._is_valid_jsonrpc_id({"k": "v"}) is False
    assert mod._is_valid_jsonrpc_id(None) is False

    with mod.SESSIONS_LOCK:
        old_bindings = dict(mod.SESSION_BINDINGS)
        old_locks = dict(mod.SESSION_RUN_LOCKS)
        old_refs = dict(mod.SESSION_LOCK_REFS)
        mod.SESSION_BINDINGS.clear()
        mod.SESSION_RUN_LOCKS.clear()
        mod.SESSION_LOCK_REFS.clear()
    try:
        pinned_lock = mod._acquire_session_lock_ref("pinned-sess")
        with mod.SESSIONS_LOCK:
            mod.SESSION_BINDINGS["pinned-sess"] = {"lastUsedAt": 1.0}
            mod.SESSION_BINDINGS["old-unpinned"] = {"lastUsedAt": 2.0}
            mod.SESSION_RUN_LOCKS["old-unpinned"] = threading.Lock()
            for idx in range(mod.MAX_RETAINED_SESSIONS + 5):
                sid = f"newer-{idx}"
                mod.SESSION_BINDINGS[sid] = {"lastUsedAt": 100.0 + idx}
                mod.SESSION_RUN_LOCKS[sid] = threading.Lock()
            mod._prune_sessions_unlocked()
            assert "pinned-sess" in mod.SESSION_BINDINGS and mod.SESSION_RUN_LOCKS.get("pinned-sess") is pinned_lock
            assert "old-unpinned" not in mod.SESSION_BINDINGS
        mod._release_session_lock_ref("pinned-sess")
        assert "pinned-sess" not in mod.SESSION_LOCK_REFS
    finally:
        with mod.SESSIONS_LOCK:
            mod.SESSION_BINDINGS.clear()
            mod.SESSION_BINDINGS.update(old_bindings)
            mod.SESSION_RUN_LOCKS.clear()
            mod.SESSION_RUN_LOCKS.update(old_locks)
            mod.SESSION_LOCK_REFS.clear()
            mod.SESSION_LOCK_REFS.update(old_refs)

    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    try:
        import pack_claude_plugin
        import zipfile
        for bad_target in ("LICENSE", "README.md"):
            try:
                pack_claude_plugin.build_plugin_archive(pack_claude_plugin.Path(bad_target))
                raise AssertionError(f"Expected ValueError when --output points to {bad_target}")
            except ValueError:
                pass
        with tempfile.TemporaryDirectory() as pk_tmp:
            out_plugin = pack_claude_plugin.build_plugin_archive(pack_claude_plugin.Path(pk_tmp) / "test.plugin")
            with zipfile.ZipFile(out_plugin, "r") as zf:
                names = zf.namelist()
            assert "assets/logo.png" not in names and ".claude-plugin/icon.png" in names, names
            assert len(names) == 9, names
    finally:
        sys.path.pop(0)

    # 19. Codex binary / argv resolution & Windows .cmd metacharacter guard (purely offline)
    orig_which = mod.shutil.which
    orig_os_name = mod.os.name
    orig_plat_machine = mod.platform.machine
    old_cb = os.environ.pop("CODEX_BIN", None)
    try:
        with tempfile.TemporaryDirectory() as res_tmp:
            npm_dir = os.path.join(res_tmp, "npm")
            cmd_shim = os.path.join(npm_dir, "codex.cmd")
            node_exe = os.path.join(res_tmp, "node.exe")
            codex_js = os.path.join(npm_dir, "node_modules", "@openai", "codex", "bin", "codex.js")
            os.makedirs(os.path.dirname(codex_js), exist_ok=True)
            for p in (cmd_shim, node_exe, codex_js):
                with open(p, "wb") as f:
                    f.write(b"")

            mod.os.name = "nt"
            mod.platform.machine = lambda: "AMD64"
            mod.shutil.which = lambda name: cmd_shim if name == "codex" else (node_exe if name == "node" else None)

            argv_js, env_js = mod._resolve_codex_argv()
            assert argv_js == [node_exe, codex_js], argv_js
            assert env_js.get("CODEX_MANAGED_BY_NPM") == "1"

            native_exe = os.path.join(
                npm_dir, "node_modules", "@openai", "codex", "node_modules",
                "@openai", "codex-win32-x64", "vendor", "x86_64-pc-windows-msvc", "codex", "codex.exe",
            )
            os.makedirs(os.path.dirname(native_exe), exist_ok=True)
            with open(native_exe, "wb") as f:
                f.write(b"")
            bin_native, env_native = mod._resolve_codex_command()
            assert bin_native == native_exe and env_native.get("CODEX_MANAGED_BY_NPM") == "1"

            mod._guard_win_batch_argv([cmd_shim, "exec", "-s", "read-only", "safe_token"])
            for bad_tok in ("a&calc", "foo|bar", "%TEMP%"):
                try:
                    mod._guard_win_batch_argv([cmd_shim, "exec", bad_tok])
                    raise AssertionError(f"Expected ValueError for batch metacharacter in {bad_tok!r}")
                except ValueError:
                    pass
    finally:
        mod.shutil.which = orig_which
        mod.os.name = orig_os_name
        mod.platform.machine = orig_plat_machine
        if old_cb is not None:
            os.environ["CODEX_BIN"] = old_cb

    # 20. Upstream app-server clientInfo stays lightweight without inline icons
    assert "icons" not in mod.CLIENT_INFO
    assert mod.CLIENT_INFO["name"] == "codex-bridge"
    assert mod.CLIENT_INFO["version"] == mod.SERVER_INFO["version"]

    print("UNIT FIXES: ALL PASSED")


def test_audit_hardening():
    # 1. CLI token validation & writable-sandbox cwd requirement
    with tempfile.TemporaryDirectory() as tmpdir:
        fc = _make_fake_codex(
            tmpdir,
            "fake_hardening",
            """import json, sys, time
args = sys.argv[1:]
_ = sys.stdin.read()
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("OK")
print(json.dumps({"type": "thread.started", "thread_id": "sess-harden-1"}))
""",
        )
        old_cb = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fc
        try:
            for field, val in (("session_id", "-bad"), ("model", "--bad"), ("profile", "bad\nline")):
                try:
                    mod.tool_exec({"prompt": "hi", field: val})
                    raise AssertionError(f"Expected ValueError for {field}={val!r}")
                except ValueError:
                    pass
            for field, val in (("base", "-main"), ("commit", "bad ref")):
                try:
                    mod.tool_review({"cwd": tmpdir, field: val})
                    raise AssertionError(f"Expected ValueError for review {field}={val!r}")
                except ValueError:
                    pass

            try:
                mod.tool_exec({"prompt": "edit", "sandbox": "workspace-write"})
                raise AssertionError("Expected ValueError for workspace-write without cwd")
            except ValueError as exc:
                assert "cwd" in str(exc)

            # Unknown argument rejection (additionalProperties: false)
            try:
                mod._dispatch_tool("codex_exec", {"prompt": "hi", "backround": True}, threading.Event())
                raise AssertionError("Expected ValueError for unknown argument")
            except ValueError as exc:
                assert "Unknown argument" in str(exc)

            # Failed/ephemeral resume must not leak SESSION_RUN_LOCKS
            with mod.SESSIONS_LOCK:
                before_locks = len(mod.SESSION_RUN_LOCKS)
            mod.tool_exec({"prompt": "ephem", "session_id": "ephem-noleak-1", "ephemeral": True})
            with mod.SESSIONS_LOCK:
                assert "ephem-noleak-1" not in mod.SESSION_RUN_LOCKS
                assert len(mod.SESSION_RUN_LOCKS) == before_locks

            # Request ID conflict check
            j_ok = mod.tool_exec({"prompt": "task-A", "cwd": tmpdir, "background": True, "request_id": "req-conflict-1"})
            try:
                mod.tool_exec({"prompt": "task-B", "cwd": tmpdir, "background": True, "request_id": "req-conflict-1"})
                raise AssertionError("Expected ValueError for conflicting request_id reuse")
            except ValueError as exc:
                assert "different request" in str(exc)
            mod.tool_job_status({"job_id": j_ok["jobId"], "wait_seconds": 10})
        finally:
            if old_cb is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_cb

    # 2. Late tool_job_cancel preserves already-published terminal status
    ev_late = threading.Event()
    with mod.JOBS_LOCK:
        mod.JOBS["late-done-1"] = {
            "jobId": "late-done-1",
            "requestId": None,
            "kind": "exec",
            "status": "completed",
            "startedAt": time.time() - 1.0,
            "lastActivityAt": time.time(),
            "finishedAt": time.time(),
            "meta": {"model": None},
            "sessionId": None,
            "agentMessagesCount": 0,
            "toolCallsCount": 0,
            "lastMessagePreview": None,
            "result": {"exitCode": 0, "response": "DONE"},
            "error": None,
            "proc": None,
            "jobObj": None,
            "doneEvent": ev_late,
        }

    def _finish_soon():
        time.sleep(0.1)
        ev_late.set()

    threading.Thread(target=_finish_soon, daemon=True).start()
    try:
        late_res = mod.tool_job_cancel({"job_id": "late-done-1"})
        assert late_res["status"] == "completed", late_res
    finally:
        with mod.JOBS_LOCK:
            mod.JOBS.pop("late-done-1", None)

    # 3. Newly created persistent background session holds mutex until Turn 1 finishes
    with tempfile.TemporaryDirectory() as race_dir:
        order_log = os.path.join(race_dir, "order.log")
        fc_race = _make_fake_codex(
            race_dir,
            "fake_session_race",
            f"""import json, sys, time
args = sys.argv[1:]
_ = sys.stdin.read()
is_resume = "resume" in args
if not is_resume:
    print(json.dumps({{"type": "thread.started", "thread_id": "sess-live-own-1"}}), flush=True)
    with open({order_log!r}, "a", encoding="utf-8") as lf:
        lf.write("turn1_start\\n")
    time.sleep(0.8)
    with open({order_log!r}, "a", encoding="utf-8") as lf:
        lf.write("turn1_end\\n")
else:
    with open({order_log!r}, "a", encoding="utf-8") as lf:
        lf.write("turn2_start\\n")
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("RACE_OK")
""",
        )
        old_cb = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fc_race
        try:
            j1 = mod.tool_exec({"prompt": "turn1", "cwd": race_dir, "background": True})
            deadline = time.monotonic() + 5.0
            seen_sid = None
            while time.monotonic() < deadline:
                st = mod.tool_job_status({"job_id": j1["jobId"]})
                if st.get("sessionId"):
                    seen_sid = st["sessionId"]
                    break
                time.sleep(0.05)
            assert seen_sid == "sess-live-own-1", st
            j2 = mod.tool_exec({"prompt": "turn2", "session_id": seen_sid, "background": True})
            r1 = mod.tool_job_status({"job_id": j1["jobId"], "wait_seconds": 10})
            r2 = mod.tool_job_status({"job_id": j2["jobId"], "wait_seconds": 10})
            assert r1["status"] == "completed" and r2["status"] == "completed", (r1, r2)
            with open(order_log, encoding="utf-8") as lf:
                events = [ln.strip() for ln in lf if ln.strip()]
            assert events == ["turn1_start", "turn1_end", "turn2_start"], events
        finally:
            if old_cb is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_cb

    # 4. Quota missing/empty/expired fallback & model pagination truncation
    assert mod._format_window({}) is None
    assert mod._format_window({"usedPercent": True}) is None

    orig_call_batch = mod.APP_SERVER.call_batch
    old_ch = os.environ.get("CODEX_HOME")
    with tempfile.TemporaryDirectory() as fake_home:
        os.environ["CODEX_HOME"] = fake_home
        try:
            mod.APP_SERVER.call_batch = lambda reqs, timeout=15.0: [
                {"result": {"account": {"type": "chatgpt"}}},
                {"result": {"ordinaryUsageAllowed": True, "rateLimits": {"primary": {}, "secondary": None}}},
            ]
            q_miss = mod.tool_quota_status({})
            assert q_miss["recommendation"]["tier"] == "unknown", q_miss

            # Expired fallback window must NOT produce use_it_or_lose_it
            sess_dir = os.path.join(fake_home, "sessions")
            os.makedirs(sess_dir, exist_ok=True)
            old_epoch = int(time.time()) - 3600
            with open(os.path.join(sess_dir, "old.jsonl"), "w", encoding="utf-8") as sf:
                sf.write(json.dumps({
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "rate_limits": {
                            "primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": old_epoch},
                            "secondary": {"usedPercent": 20, "windowDurationMins": 10080, "resetsAt": old_epoch},
                        }
                    },
                }) + "\n")

            def _boom(reqs, timeout=15.0):
                raise RuntimeError("offline")

            mod.APP_SERVER.call_batch = _boom
            q_exp = mod.tool_quota_status({})
            assert q_exp["source"] == "session-fallback"
            assert q_exp["recommendation"]["tier"] == "unknown", q_exp
            assert q_exp["staleMinutes"] and q_exp["staleMinutes"] > 60, q_exp

            # Repeated nextCursor truncates cleanly with warning
            mod.APP_SERVER.call_batch = lambda reqs, timeout=15.0: [
                {"result": {"data": [{"id": "m1", "hidden": False}], "nextCursor": "same-cur"}}
            ]
            m_res = mod.tool_list_models({})
            assert m_res.get("truncated") is True and "warning" in m_res, m_res
        finally:
            mod.APP_SERVER.call_batch = orig_call_batch
            if old_ch is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_ch

    print("AUDIT HARDENING: ALL PASSED")


def test_stderr_tail_and_queued_cancel():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_cmd = _make_fake_codex(
            tmpdir,
            "fake_codex_extra",
            """import json, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
if "STDERR_OVERFLOW" in prompt:
    sys.stderr.write("HEADER_NOISE\\n" + ("X" * 75000) + "\\nTAIL_SENTINEL_ERROR\\n")
    sys.stderr.flush()
    sys.exit(2)
time.sleep(2.5)
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("DONE")
print(json.dumps({"type": "thread.started", "thread_id": "fake-slot-1"}))
""",
        )

        old_codex_bin = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fake_cmd
        try:
            # Rolling stderr tail retention (>70 KB)
            res = mod.tool_exec({"prompt": "STDERR_OVERFLOW", "cwd": tmpdir})
            assert res["exitCode"] == 2, res
            assert "TAIL_SENTINEL_ERROR" in res.get("stderr", ""), res.get("stderr", "")[:200]
            assert "HEADER_NOISE" not in res.get("stderr", "")

            # Occupy all MAX_CONCURRENT_JOBS slots, queue one more, and cancel it immediately (< 1s)
            slot_jobs = []
            for i in range(mod.MAX_CONCURRENT_JOBS):
                j = mod.tool_exec({"prompt": f"hold-{i}", "cwd": tmpdir, "background": True})
                slot_jobs.append(j["jobId"])

            # Wait briefly so slot workers acquire JOB_SEMAPHORE
            time.sleep(0.2)
            queued = mod.tool_exec({"prompt": "queued-target", "cwd": tmpdir, "background": True})
            t0 = time.monotonic()
            cancelled = mod.tool_job_cancel({"job_id": queued["jobId"]})
            cancel_elapsed = time.monotonic() - t0
            assert cancelled["status"] == "cancelled", cancelled
            assert cancel_elapsed < 1.0, f"Queued cancel took too long: {cancel_elapsed:.2f}s"

            for jid in slot_jobs:
                mod.tool_job_cancel({"job_id": jid})
        finally:
            if old_codex_bin is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_codex_bin

    print("STDERR TAIL & QUEUED CANCEL: ALL PASSED")


def test_profile_and_images_flag_placement():
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = os.path.join(tmpdir, "screen.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        args_log = os.path.join(tmpdir, "argv_log.jsonl")
        fake_cmd = _make_fake_codex(
            tmpdir,
            "fake_codex_flags",
            f"""import json, sys
args = sys.argv[1:]
with open({args_log!r}, "a", encoding="utf-8") as lf:
    lf.write(json.dumps(args) + "\\n")
if "review" not in args:
    _ = sys.stdin.read()
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("FLAGS_OK")
print(json.dumps({{"type": "thread.started", "thread_id": "sess-flags-1"}}))
""",
        )

        old_codex_bin = os.environ.get("CODEX_BIN")
        os.environ["CODEX_BIN"] = fake_cmd
        try:
            # 1. exec with profile + images (model omitted -> -m omitted)
            r1 = mod.tool_exec({
                "prompt": "inspect screenshot",
                "cwd": tmpdir,
                "profile": "custom-prof",
                "images": [img_path],
                "ephemeral": False,
            })
            assert r1["exitCode"] == 0 and r1["profile"] == "custom-prof" and r1["imagesCount"] == 1
            assert r1["model"] is None

            # 2. resume with profile + images (-p before resume, -i after resume)
            r2 = mod.tool_exec({
                "prompt": "follow up",
                "session_id": r1["sessionId"],
                "profile": "custom-prof",
                "images": [img_path],
            })
            assert r2["exitCode"] == 0 and r2["resumed"] is True

            # 3. review with profile (-p before review, -m omitted)
            r3 = mod.tool_review({
                "cwd": tmpdir,
                "profile": "rev-prof",
                "uncommitted": True,
            })
            assert r3["exitCode"] == 0 and r3["profile"] == "rev-prof" and r3["model"] is None

            with open(args_log, encoding="utf-8") as lf:
                calls = [json.loads(line) for line in lf if line.strip()]
            assert len(calls) == 3, calls

            c1, c2, c3 = calls
            assert "-p" in c1 and c1[c1.index("-p") + 1] == "custom-prof", c1
            assert "-i" in c1 and c1[c1.index("-i") + 1] == os.path.abspath(img_path), c1
            assert "-m" not in c1, c1

            idx_res = c2.index("resume")
            assert "-p" in c2[:idx_res] and c2[c2.index("-p") + 1] == "custom-prof", c2
            assert "-i" in c2[idx_res:] and c2[c2.index("-i") + 1] == os.path.abspath(img_path), c2
            assert "-m" not in c2, c2

            idx_rev = c3.index("review")
            assert "-p" in c3[:idx_rev] and c3[c3.index("-p") + 1] == "rev-prof", c3
            assert "-m" not in c3, c3
        finally:
            if old_codex_bin is None:
                os.environ.pop("CODEX_BIN", None)
            else:
                os.environ["CODEX_BIN"] = old_codex_bin

    print("PROFILE & IMAGES FLAG PLACEMENT: ALL PASSED")


def test_mcp_concurrency_cancel_and_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_cmd = _make_fake_codex(
            tmpdir,
            "fake_codex",
            """import json, sys, time
args = sys.argv[1:]
if "review" in args:
    idx_rev = args.index("review")
    assert "-C" in args[:idx_rev] and "-s" in args[:idx_rev] and "--color" in args[:idx_rev], args
    out_idx = args.index("-o") + 1
    with open(args[out_idx], "w", encoding="utf-8") as of:
        of.write("FAKE_REVIEW_OK")
    print(json.dumps({"type": "thread.started", "thread_id": "fake-rev-1"}))
    sys.exit(0)
_ = sys.stdin.read()
time.sleep(3.0)
out_idx = args.index("-o") + 1
with open(args[out_idx], "w", encoding="utf-8") as of:
    of.write("FAKE_EXEC_OK")
print(json.dumps({"type": "thread.started", "thread_id": "fake-exec-1"}))
""",
        )

        env = os.environ.copy()
        env["CODEX_BIN"] = fake_cmd
        env["PYTHONINTMAXSTRDIGITS"] = "4300"

        proc = subprocess.Popen(
            [sys.executable, "-u", SERVER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin and proc.stdout

        responses = {}
        raw_messages = []
        resp_lock = threading.Lock()

        def reader():
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                msg = json.loads(raw.decode("utf-8"))
                with resp_lock:
                    raw_messages.append(msg)
                    if isinstance(msg, dict) and "id" in msg:
                        responses[msg["id"]] = msg

        threading.Thread(target=reader, daemon=True).start()

        def send(obj):
            proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            proc.stdin.flush()

        def wait_id(mid, timeout=10.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with resp_lock:
                    if mid in responses:
                        return responses.pop(mid)
                time.sleep(0.02)
            raise TimeoutError(f"Timeout waiting for id={mid}")

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        init_res = wait_id(1)["result"]
        server_info = init_res["serverInfo"]
        assert server_info["name"] == "codex-bridge"
        assert server_info["title"] == "Codex GPT Bridge"
        icons = server_info.get("icons")
        assert isinstance(icons, list) and len(icons) >= 1, server_info
        icon0 = icons[0]
        assert icon0["mimeType"] == "image/png", icon0
        assert icon0["sizes"] == ["96x96"], icon0
        assert icon0["src"].startswith("data:image/png;base64,"), icon0
        raw_icon = base64.b64decode(icon0["src"].split(",", 1)[1])
        assert 0 < len(raw_icon) < 10_000, len(raw_icon)
        assert len(json.dumps(server_info, separators=(",", ":"))) < 16_000
        assert init_res["protocolVersion"] == "2025-06-18", init_res

        send({"jsonrpc": "2.0", "id": 103, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}})
        assert wait_id(103)["result"]["protocolVersion"] == "2024-11-05"
        send({"jsonrpc": "2.0", "id": 104, "method": "initialize", "params": {}})
        assert wait_id(104)["result"]["protocolVersion"] == "2024-11-05"

        send({"jsonrpc": "2.0", "id": 101, "method": "resources/list", "params": {}})
        assert wait_id(101)["result"] == {"resources": []}
        send({"jsonrpc": "2.0", "id": 105, "method": "resources/templates/list", "params": {}})
        assert wait_id(105)["result"] == {"resourceTemplates": []}
        send({"jsonrpc": "2.0", "id": 102, "method": "prompts/list", "params": {}})
        assert wait_id(102)["result"] == {"prompts": []}

        send({"jsonrpc": "2.0", "id": 106, "method": "tools/call", "params": {"name": "codex_job_cancel", "arguments": {"job_id": "__probe_missing_job__"}}})
        r_missing = wait_id(106, timeout=3.0)["result"]
        assert r_missing["isError"] is True, r_missing
        err_obj = json.loads(r_missing["content"][0]["text"])
        assert err_obj["error"]["code"] == "ValueError" and "__probe_missing_job__" in err_obj["error"]["message"], err_obj

        # Malformed envelopes must return JSON-RPC errors without crashing or leaking CANCEL_EVENTS
        send({"jsonrpc": "2.0", "id": [1, 2], "method": "ping", "params": {}})
        err_bad_id = wait_id(None, timeout=2.0)["error"]
        assert err_bad_id["code"] == -32600, err_bad_id
        send({"jsonrpc": "2.0", "id": None, "method": "ping", "params": {}})
        err_null_id = wait_id(None, timeout=2.0)["error"]
        assert err_null_id["code"] == -32600, err_null_id
        proc.stdin.write(('{"jsonrpc":"2.0","id":' + ("9" * 5000) + ',"method":"ping"}\n').encode("utf-8"))
        proc.stdin.flush()
        err_huge_id = wait_id(None, timeout=2.0)["error"]
        assert err_huge_id["code"] == -32700, err_huge_id
        send({"jsonrpc": "2.0", "id": 109, "method": "ping", "params": [1]})
        err_bad_params = wait_id(109, timeout=2.0)["error"]
        assert err_bad_params["code"] == -32602, err_bad_params
        send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": [99]}})
        send({"jsonrpc": "2.0", "id": 107, "method": "tools/call", "params": {"name": "codex_quota_status", "arguments": ["bad"]}})
        err_bad_args = wait_id(107, timeout=2.0)["error"]
        assert err_bad_args["code"] == -32602, err_bad_args
        send({"jsonrpc": "2.0", "id": 110, "method": "tools/call", "params": {"name": "codex_quota_status", "arguments": None}})
        err_null_args = wait_id(110, timeout=2.0)["error"]
        assert err_null_args["code"] == -32602, err_null_args
        send({"jsonrpc": "2.0", "id": 108, "method": "ping", "params": {}})
        assert wait_id(108, timeout=2.0)["result"] == {}

        # Strict jsonrpc "2.0" / empty-object / ID-bearing notification / batch rejection checks
        send({"id": 111, "method": "ping", "params": {}})
        assert wait_id(111, timeout=2.0)["error"]["code"] == -32600
        send({"jsonrpc": "1.0", "id": 112, "method": "ping", "params": {}})
        assert wait_id(112, timeout=2.0)["error"]["code"] == -32600
        send({})
        assert wait_id(None, timeout=2.0)["error"]["code"] == -32600
        send({"jsonrpc": "2.0", "id": 113, "method": "notifications/cancelled", "params": {"requestId": 4}})
        assert wait_id(113, timeout=2.0)["error"]["code"] == -32601
        send([{"jsonrpc": "2.0", "id": 114, "method": "ping"}])
        assert wait_id(None, timeout=2.0)["error"]["code"] == -32600
        send({"jsonrpc": "2.0", "id": 115, "method": "tools/call", "params": {"name": "codex_exec", "arguments": {"prompt": "hi", "badKey": 1}}})
        r_unknown = wait_id(115, timeout=2.0)["result"]
        assert r_unknown["isError"] is True and "Unknown argument" in r_unknown["content"][0]["text"], r_unknown

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "codex_exec", "arguments": {"prompt": "slow", "background": True, "request_id": "req-1"}}})
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "codex_exec", "arguments": {"prompt": "slow", "background": True, "request_id": "req-1"}}})
        r2 = json.loads(wait_id(2)["result"]["content"][0]["text"])
        r3 = json.loads(wait_id(3)["result"]["content"][0]["text"])
        assert r2["jobId"] == r3["jobId"] and (bool(r2.get("deduplicated")) != bool(r3.get("deduplicated"))), (r2, r3)

        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "codex_job_status", "arguments": {"job_id": r2["jobId"], "wait_seconds": 20}}})
        time.sleep(0.15)
        t_ping = time.monotonic()
        send({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}})
        wait_id(5, timeout=1.0)
        ping_ms = (time.monotonic() - t_ping) * 1000
        assert ping_ms < 500, f"ping blocked by wait! {ping_ms}ms"

        t_cancel_wait = time.monotonic()
        send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 4}})
        r4 = wait_id(4, timeout=2.0)
        assert (time.monotonic() - t_cancel_wait) < 1.5
        assert json.loads(r4["result"]["content"][0]["text"])["status"] in ("starting", "running", "queued", "completed")

        send({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "codex_job_cancel", "arguments": {"job_id": r2["jobId"]}}})
        r6 = json.loads(wait_id(6, timeout=8.0)["result"]["content"][0]["text"])
        assert r6["status"] == "cancelled", r6

        send({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "codex_review", "arguments": {"cwd": tmpdir, "uncommitted": True}}})
        r7_raw = wait_id(7, timeout=5.0)
        assert r7_raw["result"]["isError"] is False, r7_raw
        r7 = json.loads(r7_raw["result"]["content"][0]["text"])
        assert r7["response"] == "FAKE_REVIEW_OK" and r7["reviewMode"] == "cli-review", r7

        proc.terminate()
        proc.wait(timeout=3)

        # Dedicated MCP 2025-03-26 JSON-RPC batch test
        batch_proc = subprocess.Popen(
            [sys.executable, "-u", SERVER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert batch_proc.stdin and batch_proc.stdout
        batch_input = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps([
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            ]),
            json.dumps([{"jsonrpc": "2.0", "method": "notifications/initialized"}]),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}),
        ]) + "\n"
        out_bytes, _ = batch_proc.communicate(batch_input.encode("utf-8"), timeout=10)
        out_lines = [json.loads(ln) for ln in out_bytes.decode("utf-8").splitlines() if ln.strip()]
        assert len(out_lines) == 3, out_lines
        assert out_lines[0]["result"]["protocolVersion"] == "2025-03-26"
        assert isinstance(out_lines[1], list) and [x["id"] for x in out_lines[1]] == [2, 3], out_lines[1]
        assert out_lines[2]["id"] == 4 and out_lines[2]["result"] == {}, out_lines[2]

        print(f"MCP CONCURRENCY/CANCEL/REVIEW: ALL PASSED (ping={ping_ms:.1f}ms during 20s wait)")


def run_live_codex():
    q = mod.tool_quota_status({})
    assert q["source"] == "codex-app-server-live"
    assert q["recommendation"]["tier"] != "unknown"
    p_rem = (q.get("primary5hWindow") or {}).get("remainingPercent")
    s_rem = (q.get("secondary7dWindow") or {}).get("remainingPercent")
    print("LIVE QUOTA TIER:", q["recommendation"]["tier"], "5h rem:", p_rem, "7d rem:", s_rem)

    m = mod.tool_list_models({"include_hidden": True})
    assert m["source"] == "codex-app-server-live" and len(m["models"]) > 0
    print("LIVE MODELS COUNT (include_hidden=True):", len(m["models"]))

    with tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
        fpath = os.path.join(repo, "app.py")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")
        subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a - b  # bug\n")

        rev = mod.tool_review({"cwd": repo, "model": "gpt-6-luna", "reasoning_effort": "low", "uncommitted": True})
        print("LIVE REVIEW EXIT:", rev["exitCode"], "MODE:", rev["reviewMode"], "PREVIEW:", rev["response"][:160].replace("\n", " "))
        assert rev["exitCode"] == 0, rev

    mod.APP_SERVER.close()
    print("LIVE CODEX SMOKE: ALL PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Also run live Codex CLI smoke tests.")
    args = parser.parse_args()
    test_unit_fixes()
    test_audit_hardening()
    test_stderr_tail_and_queued_cancel()
    test_profile_and_images_flag_placement()
    test_mcp_concurrency_cancel_and_idempotency()
    if args.live:
        run_live_codex()
