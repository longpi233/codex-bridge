import argparse
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

    # 4. Missing rate-limit windows -> unknown, NOT abundant
    rec = mod._compute_recommendation(None, None, None)
    assert rec["tier"] == "unknown", rec

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

    # 8. _git_fingerprint changes when tracked file diff changes (mocked for sandbox portability)
    orig_subproc_run = mod.subprocess.run
    try:
        diff_payload = [b"diff --git a/a.py b/a.py\n-x = 1\n+x = 2\n"]

        def fake_git_run(cmd, **kwargs):
            class Res:
                def __init__(self, returncode, stdout):
                    self.returncode = returncode
                    self.stdout = stdout

            if "rev-parse" in cmd:
                return Res(0, b"deadbeef\n")
            if "status" in cmd:
                return Res(0, b" M a.py\n")
            if "diff" in cmd:
                return Res(0, diff_payload[0])
            raise AssertionError(f"Unexpected command: {cmd}")

        mod.subprocess.run = fake_git_run
        fp1 = mod._git_fingerprint(REPO_ROOT)
        diff_payload[0] = b"diff --git a/a.py b/a.py\n-x = 1\n+x = 3\n"
        fp2 = mod._git_fingerprint(REPO_ROOT)
        assert fp1 is not None and fp2 is not None
        assert fp1 != fp2, f"Expected fingerprint to change when diff changed: {fp1} vs {fp2}"
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

    # 13. Codex binary resolution (native codex.exe on Windows when installed via npm)
    codex_bin, env = mod._resolve_codex_command()
    print("Resolved codex_bin:", codex_bin)
    if os.name == "nt" and "codex-win32" in codex_bin.lower():
        assert codex_bin.lower().endswith("codex.exe")
        assert env.get("CODEX_MANAGED_BY_NPM") == "1"

    print("UNIT FIXES: ALL PASSED")


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

        proc = subprocess.Popen(
            [sys.executable, "-u", SERVER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin and proc.stdout

        responses = {}
        resp_lock = threading.Lock()

        def reader():
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                msg = json.loads(raw.decode("utf-8"))
                if "id" in msg:
                    with resp_lock:
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

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert wait_id(1)["result"]["serverInfo"]["name"] == "codex-bridge"

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "codex_exec", "arguments": {"prompt": "slow", "background": True, "request_id": "req-1"}}})
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "codex_exec", "arguments": {"prompt": "slow", "background": True, "request_id": "req-1"}}})
        r2 = json.loads(wait_id(2)["result"]["content"][0]["text"])
        r3 = json.loads(wait_id(3)["result"]["content"][0]["text"])
        assert r2["jobId"] == r3["jobId"] and r3.get("deduplicated") is True, (r2, r3)

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
        print(f"MCP CONCURRENCY/CANCEL/REVIEW: ALL PASSED (ping={ping_ms:.1f}ms during 20s wait)")


def test_live_codex():
    q = mod.tool_quota_status({})
    assert q["source"] == "codex-app-server-live"
    assert q["recommendation"]["tier"] != "unknown"
    print("LIVE QUOTA TIER:", q["recommendation"]["tier"], "5h rem:", q["primary5hWindow"]["remainingPercent"], "7d rem:", q["secondary7dWindow"]["remainingPercent"])

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
    test_stderr_tail_and_queued_cancel()
    test_profile_and_images_flag_placement()
    test_mcp_concurrency_cancel_and_idempotency()
    if args.live:
        test_live_codex()
