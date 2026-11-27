#!/usr/bin/env python3
"""Standard MCP stdio server bridging AI coding agents to the local OpenAI Codex CLI.

Cross-platform & cross-agent (Antigravity, Claude Code, Cursor, Windsurf, etc.):
- Live quota, rate-limit window, and reset-time-paced task routing via Codex app-server.
- Model discovery with pagination & hidden-model support.
- Non-interactive `codex exec` (with `-p` profile, `-i` images, and multi-turn `session_id` resume)
  and `codex_review`.
- Async background jobs (`background: true`) with bounded concurrency, cancellation,
  idempotent `request_id`, and full process-tree cleanup (Windows Job Object / POSIX `killpg`).
- Strict UTF-8 MCP stdio + UTF-8/locale (CP936/GBK) child-output decoding fallback.
"""

from __future__ import annotations

import collections
import concurrent.futures
import ctypes
import glob
import hashlib
import json
import locale
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any


SERVER_INFO = {
    "name": "codex-bridge",
    "version": "0.2.0",
}
PROTOCOL_VERSION = "2024-11-05"

MAX_CONCURRENT_JOBS = 4
MAX_QUEUED_JOBS = 20
MAX_RETAINED_FINISHED_JOBS = 50
MAX_RETAINED_SESSIONS = 200
MAX_IMAGES_PER_CALL = 10
FINISHED_JOB_TTL_SECONDS = 1800.0
MAX_STDERR_BYTES = 65536
VALID_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
VALID_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")

SEND_LOCK = threading.Lock()
CANCEL_LOCK = threading.Lock()
CANCEL_EVENTS: dict[Any, threading.Event] = {}

JOBS_LOCK = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}
REQUEST_ID_TO_JOB: dict[str, str] = {}
JOB_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_JOBS)

SESSIONS_LOCK = threading.Lock()
SESSION_BINDINGS: dict[str, dict[str, Any]] = {}
SESSION_RUN_LOCKS: dict[str, threading.Lock] = {}


def _configure_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _decode_bytes(raw: bytes) -> str:
    """Decode subprocess bytes cleanly: strict UTF-8 first, then Windows ACP / OS locale."""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    candidates: list[str] = []
    if os.name == "nt":
        try:
            acp = ctypes.windll.kernel32.GetACP()
            if acp:
                candidates.append(f"cp{acp}")
        except Exception:
            pass
        candidates.append("mbcs")
    pref = locale.getpreferredencoding(False)
    if pref:
        candidates.append(pref)
    for enc in candidates:
        if enc.lower().replace("-", "") == "utf8":
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def _resolve_codex_command() -> tuple[str, dict[str, str]]:
    """Resolve native `codex.exe` when possible to skip `.cmd` + `node.exe` wrapper overhead."""
    env = os.environ.copy()
    override = env.get("CODEX_BIN")
    if override and os.path.isfile(override):
        return override, env

    which_path = shutil.which("codex")
    if not which_path:
        raise FileNotFoundError(
            "Codex CLI ('codex') was not found in PATH. Install it or set CODEX_BIN."
        )

    if os.name == "nt" and which_path.lower().endswith((".cmd", ".bat")):
        npm_dir = os.path.dirname(which_path)
        pkg_root = os.path.join(npm_dir, "node_modules", "@openai", "codex")
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            arch_order = (
                ("codex-win32-arm64", "aarch64-pc-windows-msvc"),
                ("codex-win32-x64", "x86_64-pc-windows-msvc"),
            )
        else:
            arch_order = (
                ("codex-win32-x64", "x86_64-pc-windows-msvc"),
                ("codex-win32-arm64", "aarch64-pc-windows-msvc"),
            )
        for pkg_name, target_triple in arch_order:
            for base_dir in (
                os.path.join(pkg_root, "node_modules", "@openai", pkg_name, "vendor"),
                os.path.join(npm_dir, "node_modules", "@openai", pkg_name, "vendor"),
            ):
                if not os.path.isdir(base_dir):
                    continue
                for sub_dir in ("codex", "bin"):
                    candidate = os.path.join(base_dir, target_triple, sub_dir, "codex.exe")
                    if os.path.isfile(candidate):
                        env["CODEX_MANAGED_BY_NPM"] = "1"
                        if os.path.isdir(pkg_root):
                            env["CODEX_MANAGED_PACKAGE_ROOT"] = pkg_root
                        return candidate, env

    return which_path, env


class _WinJobObject:
    """Windows Job Object ensuring the whole child process tree is killed on close/terminate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.handle: Any = None
        if os.name != "nt":
            return
        try:
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            self._kernel32 = kernel32
            h = kernel32.CreateJobObjectW(None, None)
            if not h:
                return

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000) | JOB_OBJECT_LIMIT_BREAKAWAY_OK (0x800)
            info.BasicLimitInformation.LimitFlags = 0x2000 | 0x800
            JobObjectExtendedLimitInformation = 9
            ok = kernel32.SetInformationJobObject(
                h,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if ok:
                self.handle = h
            else:
                kernel32.CloseHandle(h)
        except Exception:
            self.handle = None

    def assign(self, proc: subprocess.Popen[bytes]) -> None:
        if os.name != "nt":
            return
        with self._lock:
            if not self.handle:
                return
            try:
                proc_handle = getattr(proc, "_handle", None)
                if proc_handle:
                    self._kernel32.AssignProcessToJobObject(self.handle, int(proc_handle))
            except Exception:
                pass

    def terminate_tree(self) -> None:
        if os.name != "nt":
            return
        with self._lock:
            if not self.handle:
                return
            try:
                self._kernel32.TerminateJobObject(self.handle, 1)
            except Exception:
                pass

    def close(self) -> None:
        if os.name != "nt":
            return
        with self._lock:
            handle, self.handle = self.handle, None
        if not handle:
            return
        try:
            self._kernel32.CloseHandle(handle)
        except Exception:
            pass


def _terminate_process_tree(proc: subprocess.Popen[bytes], job_obj: _WinJobObject | None) -> None:
    if job_obj is not None:
        job_obj.terminate_tree()
    try:
        if proc.poll() is None:
            if os.name != "nt":
                pgid = getattr(proc, "pid", None)
                killed_group = False
                if isinstance(pgid, int) and pgid > 0:
                    try:
                        os.killpg(pgid, signal.SIGTERM)
                        killed_group = True
                    except OSError:
                        proc.terminate()
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    if killed_group and isinstance(pgid, int) and pgid > 0:
                        try:
                            os.killpg(pgid, signal.SIGKILL)
                        except OSError:
                            proc.kill()
                    else:
                        proc.kill()
                    proc.wait(timeout=2.0)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
        else:
            proc.wait(timeout=0.5)
    except Exception:
        pass
    if job_obj is not None:
        job_obj.close()


class _AppServerClient:
    """Supervised, auto-reconnecting stdio JSON-RPC client for `codex app-server`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._job_obj: _WinJobObject | None = None
        self._next_id = 1
        self._pending: dict[int, tuple[threading.Event, list[Any]]] = {}
        self._pending_lock = threading.Lock()
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=40)

    def _stop_unlocked(self) -> None:
        proc = self._proc
        job_obj = self._job_obj
        self._proc = None
        self._job_obj = None
        with self._pending_lock:
            for ev, box in self._pending.values():
                box.append({"error": {"message": "codex app-server disconnected"}})
                ev.set()
            self._pending.clear()
        if proc is not None:
            _terminate_process_tree(proc, job_obj)

    def _start_unlocked(self, timeout: float = 15.0) -> None:
        self._stop_unlocked()
        codex_bin, env = _resolve_codex_command()
        job_obj = _WinJobObject()
        proc = subprocess.Popen(
            [codex_bin, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=(os.name != "nt"),
        )
        job_obj.assign(proc)
        self._proc = proc
        self._job_obj = job_obj
        self._stderr_tail.clear()

        def _read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                text = _decode_bytes(raw).strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and "id" in msg:
                    msg_id = msg["id"]
                    with self._pending_lock:
                        if self._proc is not proc:
                            entry = None
                        else:
                            entry = self._pending.pop(msg_id, None)
                    if entry is not None:
                        ev, box = entry
                        box.append(msg)
                        ev.set()
            # EOF reached: wake any remaining waiters belonging to this process instance
            with self._pending_lock:
                if self._proc is proc:
                    for ev, box in self._pending.values():
                        if not box:
                            box.append({"error": {"message": "codex app-server closed stdout"}})
                        ev.set()
                    self._pending.clear()

        def _read_stderr() -> None:
            assert proc.stderr is not None
            while True:
                raw = proc.stderr.readline()
                if not raw:
                    break
                line = _decode_bytes(raw).rstrip()
                if line:
                    self._stderr_tail.append(line)

        threading.Thread(target=_read_stdout, daemon=True).start()
        threading.Thread(target=_read_stderr, daemon=True).start()

        # Codex app-server handshake: initialize -> wait result -> initialized
        init_resp = self._send_rpc_unlocked(
            "initialize",
            {"clientInfo": SERVER_INFO, "capabilities": {}},
            timeout=timeout,
        )
        if "error" in init_resp:
            err = init_resp["error"]
            self._stop_unlocked()
            raise RuntimeError(f"codex app-server initialize error: {err}")

        self._send_notify_unlocked("initialized", {})

    def _send_notify_unlocked(self, method: str, params: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("codex app-server stdin unavailable")
        line = (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode("utf-8")
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _send_rpc_unlocked(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin or self._proc.poll() is not None:
            raise RuntimeError("codex app-server is not running")
        req_id = self._next_id
        self._next_id += 1
        ev = threading.Event()
        box: list[Any] = []
        with self._pending_lock:
            self._pending[req_id] = (ev, box)
        try:
            payload = (json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n").encode("utf-8")
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except Exception as exc:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise RuntimeError(f"Failed to send {method} to app-server: {exc}") from exc

        if not ev.wait(timeout=timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            tail = " | ".join(list(self._stderr_tail)[-5:])
            raise TimeoutError(f"codex app-server timed out on {method} after {timeout}s. {tail}")

        return box[0] if box else {"error": {"message": f"No response for {method}"}}

    def call_batch(
        self,
        requests: list[tuple[str, dict[str, Any]]],
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        with self._lock:
            last_err: Exception | None = None
            for attempt in range(2):
                try:
                    if self._proc is None or self._proc.poll() is not None or attempt == 1:
                        self._start_unlocked(timeout=timeout)
                    deadline = time.monotonic() + timeout
                    out: list[dict[str, Any]] = []
                    for method, params in requests:
                        rem = max(1.0, deadline - time.monotonic())
                        out.append(self._send_rpc_unlocked(method, params, timeout=rem))
                    return out
                except Exception as exc:
                    last_err = exc
                    self._stop_unlocked()
            raise RuntimeError(f"codex app-server call failed: {last_err}")

    def close(self) -> None:
        with self._lock:
            self._stop_unlocked()


APP_SERVER = _AppServerClient()


def _as_bool(val: Any, default: bool, name: str) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    raise ValueError(f"'{name}' must be a boolean, got {type(val).__name__}: {val!r}")


def _as_int(val: Any, default: int, name: str, minimum: int, maximum: int) -> int:
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"'{name}' must be an integer, got {val!r}")
    return max(minimum, min(maximum, val))


def _resolve_timeout_seconds(val: Any, reasoning_effort: str | None) -> int:
    """Resolve timeout_seconds: 900s/1800s defaults, 180s/300s floors, up to 3600s, or 0 for no hard limit."""
    is_heavy = reasoning_effort in ("high", "xhigh", "max", "ultra")
    if val is not None and not isinstance(val, bool) and val == 0:
        return 0
    default = 1800 if is_heavy else 900
    floor = 300 if is_heavy else 180
    return _as_int(val, default, "timeout_seconds", floor, 3600)


def _as_float(val: Any, default: float, name: str, minimum: float, maximum: float) -> float:
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"'{name}' must be a number, got {val!r}")
    return max(minimum, min(maximum, float(val)))


def _validate_cwd(cwd: Any, required: bool = False) -> str | None:
    if cwd is None:
        if required:
            raise ValueError("'cwd' is required and must be an existing directory path.")
        return None
    if not isinstance(cwd, str) or not cwd.strip():
        raise ValueError("'cwd' must be a non-empty directory path string.")
    cleaned = cwd.strip().strip('"').strip("'")
    norm = os.path.abspath(os.path.expanduser(cleaned))
    if not os.path.isdir(norm):
        raise ValueError(f"Working directory does not exist or is not a directory: {norm}")
    return norm


def _validate_profile(profile: Any) -> str | None:
    if profile is None:
        return None
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("'profile' must be a non-empty string.")
    cleaned = profile.strip()
    if cleaned.startswith("-"):
        raise ValueError("'profile' must not start with '-'.")
    return cleaned


def _validate_images(images: Any) -> list[str]:
    if images is None:
        return []
    if not isinstance(images, list):
        raise ValueError("'images' must be an array of file path strings.")
    if len(images) > MAX_IMAGES_PER_CALL:
        raise ValueError(f"'images' supports at most {MAX_IMAGES_PER_CALL} files per call.")
    validated: list[str] = []
    for idx, item in enumerate(images):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"'images[{idx}]' must be a non-empty file path string.")
        cleaned = item.strip().strip('"').strip("'")
        norm = os.path.abspath(os.path.expanduser(cleaned))
        if not os.path.isfile(norm):
            raise ValueError(f"Image file does not exist or is not a file: {norm}")
        validated.append(norm)
    return validated


def _format_epoch_local(ts: Any) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _prune_sessions_unlocked() -> None:
    if len(SESSION_BINDINGS) <= MAX_RETAINED_SESSIONS:
        return
    candidates = sorted(
        SESSION_BINDINGS.items(),
        key=lambda kv: kv[1].get("lastUsedAt", 0.0),
    )
    excess = len(SESSION_BINDINGS) - MAX_RETAINED_SESSIONS
    removed = 0
    for sid, _ in candidates:
        if removed >= excess:
            break
        lock = SESSION_RUN_LOCKS.get(sid)
        if lock is not None and lock.locked():
            continue
        SESSION_BINDINGS.pop(sid, None)
        SESSION_RUN_LOCKS.pop(sid, None)
        removed += 1


def _format_window(win: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(win, dict):
        return None
    used = win.get("usedPercent", win.get("used_percent"))
    duration = win.get("windowDurationMins", win.get("window_minutes"))
    resets_at = win.get("resetsAt", win.get("resets_at"))
    remaining = round(max(0.0, 100.0 - float(used)), 2) if used is not None else None

    resets_local = None
    resets_utc = None
    minutes_until_reset = None
    if isinstance(resets_at, (int, float)):
        now_ts = time.time()
        minutes_until_reset = round(max(0.0, (resets_at - now_ts) / 60.0), 1)
        resets_utc = datetime.fromtimestamp(resets_at, tz=timezone.utc).isoformat()
        resets_local = datetime.fromtimestamp(resets_at).astimezone().isoformat()

    return {
        "usedPercent": used,
        "remainingPercent": remaining,
        "windowDurationMins": duration,
        "resetsAtEpoch": resets_at,
        "resetsAtLocal": resets_local,
        "resetsAtUtc": resets_utc,
        "minutesUntilReset": minutes_until_reset,
    }


def _surplus_ratio(remaining_pct: float | None, mins_until_reset: float | None, window_mins: Any) -> float | None:
    """Ratio of remaining quota % to remaining time % in the window (>1.0 = ahead of pace)."""
    if remaining_pct is None or mins_until_reset is None or not window_mins:
        return None
    time_rem_pct = max(0.5, min(100.0, (float(mins_until_reset) / float(window_mins)) * 100.0))
    return round(float(remaining_pct) / time_rem_pct, 2)


def _classify_windows(
    raw_primary: dict[str, Any] | None,
    raw_secondary: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Normalize rate-limit windows into (short_window_5h, long_window_7d) using windowDurationMins."""
    w1 = _format_window(raw_primary)
    w2 = _format_window(raw_secondary)
    d1 = w1.get("windowDurationMins") if w1 else None
    d2 = w2.get("windowDurationMins") if w2 else None
    is_long_1 = isinstance(d1, (int, float)) and d1 >= 1440
    is_short_2 = isinstance(d2, (int, float)) and d2 < 1440

    if w1 is not None and w2 is None:
        return (None, w1) if is_long_1 else (w1, None)
    if w1 is None and w2 is not None:
        return (w2, None) if is_short_2 else (None, w2)
    if w1 is not None and w2 is not None and is_long_1 and is_short_2:
        return (w2, w1)
    return (w1, w2)


def _compute_recommendation(
    ordinary_allowed: bool | None,
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
    *,
    credits: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend model, reasoning effort, and diverse task strategies based on quota & reset pacing."""
    p_rem = primary.get("remainingPercent") if primary else None
    p_mins = primary.get("minutesUntilReset") if primary else None
    p_dur = primary.get("windowDurationMins") if primary else 300
    p_ratio = _surplus_ratio(p_rem, p_mins, p_dur)

    s_rem = secondary.get("remainingPercent") if secondary else None
    s_mins = secondary.get("minutesUntilReset") if secondary else None
    s_dur = secondary.get("windowDurationMins") if secondary else 10080
    s_ratio = _surplus_ratio(s_rem, s_mins, s_dur)

    pacing = {
        "primary5hSurplusRatio": p_ratio,
        "secondary7dSurplusRatio": s_ratio,
        "note": "SurplusRatio > 1.0 means remaining quota % exceeds remaining time % in that window.",
    }

    if ordinary_allowed is False or (p_rem is not None and p_rem < 3) or (s_rem is not None and s_rem < 3):
        return {
            "tier": "exhausted",
            "strategy": "wait_for_reset",
            "allowDelegation": False,
            "recommendedModel": None,
            "recommendedReasoningEffort": None,
            "suggestedUseCases": [
                "Handle verification locally in Antigravity until the blocking window resets.",
                "Optionally consume a RateLimitResetCredit in Codex if urgent.",
            ],
            "avoidUseCases": ["All codex_exec / codex_review calls"],
            "pacingMetrics": pacing,
            "guidance": "Codex quota is exhausted (<3% or blocked). Do not delegate until reset.",
        }

    if isinstance(credits, dict) and credits.get("unlimited") is True:
        return {
            "tier": "unlimited",
            "strategy": "free_delegation",
            "allowDelegation": True,
            "recommendedModel": "gpt-6.2-astra",
            "recommendedReasoningEffort": "high",
            "alternativeModel": "gpt-6.2-sol",
            "alternativeReasoningEffort": "medium",
            "suggestedUseCases": [
                "Deep architecture, security, and root-cause audits (gpt-6.2-astra, high/xhigh).",
                "Pre-commit / pre-merge codex_review and parallel background subtasks.",
            ],
            "avoidUseCases": ["Trivial one-line questions that your main agent can answer directly."],
            "pacingMetrics": pacing,
            "guidance": (
                "Account has unlimited Codex credits. Freely delegate complex verification "
                "to gpt-6.2-astra (high) or parallel tasks to gpt-6.2-sol (medium/high)."
            ),
        }

    if primary is None and secondary is None:
        if isinstance(account, dict) and account.get("type") == "apiKey":
            return {
                "tier": "api_payg",
                "strategy": "cost_aware_delegation",
                "allowDelegation": True,
                "recommendedModel": "gpt-6.2-sol",
                "recommendedReasoningEffort": "medium",
                "alternativeModel": "gpt-6.2-astra",
                "alternativeReasoningEffort": "high",
                "suggestedUseCases": [
                    "Standard code reviews and bounded checks (gpt-6.2-sol, medium).",
                    "Targeted gpt-6.2-astra (high) verification on complex or high-risk diffs.",
                ],
                "avoidUseCases": ["Unbounded whole-repo scans without file targets (pay-as-you-go billing)."],
                "pacingMetrics": pacing,
                "guidance": (
                    "Account uses API-key pay-as-you-go billing with no rolling 5h/7d window limits. "
                    "Default to gpt-6.2-sol (medium) and reserve gpt-6.2-astra (high) for critical paths."
                ),
            }
        return {
            "tier": "unknown",
            "strategy": "verify_quota_before_heavy_delegation",
            "allowDelegation": None,
            "recommendedModel": "gpt-6.2-sol",
            "recommendedReasoningEffort": "low",
            "suggestedUseCases": [
                "Quota window data was unavailable; start with a small gpt-6.2-sol (low) check.",
            ],
            "avoidUseCases": ["Heavy xhigh/max audits until quota status is confirmed."],
            "pacingMetrics": {"primary5hSurplusRatio": None, "secondary7dSurplusRatio": None},
            "guidance": "Rate-limit windows were missing from the response. Proceed conservatively.",
        }

    weekly_burn_opportunity = (
        s_rem is not None
        and s_mins is not None
        and ((s_mins <= 24 * 60 and s_rem >= 15 and (s_ratio or 0) >= 1.5) or (s_mins <= 6 * 60 and s_rem >= 8))
        and (p_rem is None or p_rem >= 15)
    )
    primary_burn_opportunity = (
        p_rem is not None
        and p_mins is not None
        and p_mins <= 60
        and p_rem >= 25
        and (s_rem is None or s_rem >= 20)
    )

    if weekly_burn_opportunity or primary_burn_opportunity:
        reason = (
            f"Weekly reset is in {round(s_mins / 60, 1)}h with {s_rem}% left (surplus {s_ratio}x)."
            if weekly_burn_opportunity and s_mins is not None
            else f"5h reset is in {p_mins}m with {p_rem}% left."
        )
        return {
            "tier": "use_it_or_lose_it",
            "strategy": "maximize_burn_before_reset",
            "allowDelegation": True,
            "recommendedModel": "gpt-6.2-astra",
            "recommendedReasoningEffort": "xhigh",
            "alternativeModel": "gpt-6.2-sol",
            "alternativeReasoningEffort": "high",
            "suggestedUseCases": [
                "Deep module/repo architectural & security audits (gpt-6.2-astra, xhigh, background: true).",
                "Parallel codex_worker subagents or background batches across modules.",
                "Thorough edge-case hunting, refactoring proposals, and test-suite generation.",
                "Cross-model second opinions on every non-trivial change before reset.",
            ],
            "avoidUseCases": ["Holding back unnecessarily — unused quota expires at reset."],
            "pacingMetrics": pacing,
            "guidance": (
                f"Reset is approaching with surplus quota ({reason}) "
                "Prefer generous, high-value delegation (gpt-6.2-astra high/xhigh or parallel gpt-6.2-sol) "
                "to utilize remaining balance before it expires."
            ),
        }

    effective_rem = min([v for v in (p_rem, s_rem) if v is not None], default=100.0)

    if effective_rem >= 50:
        if primary is not None and secondary is not None:
            abundant_desc = "Both 5h and 7d quotas are abundant (>=50% remaining)."
        elif secondary is not None:
            abundant_desc = f"Weekly 7d quota is abundant ({s_rem}% remaining; no 5h window limit)."
        else:
            abundant_desc = f"5h quota is abundant ({p_rem}% remaining; no 7d window limit)."
        return {
            "tier": "abundant",
            "strategy": "free_delegation",
            "allowDelegation": True,
            "recommendedModel": "gpt-6.2-astra",
            "recommendedReasoningEffort": "high",
            "alternativeModel": "gpt-6.2-sol",
            "alternativeReasoningEffort": "medium",
            "suggestedUseCases": [
                "Complex bug root-cause analysis and design verification (gpt-6.2-astra, high).",
                "Pre-commit / pre-merge codex_review on feature diffs.",
                "Bounded implementation subtasks via codex_worker (gpt-6.2-sol, medium/high).",
            ],
            "avoidUseCases": ["Trivial one-line questions that Antigravity can answer directly."],
            "pacingMetrics": pacing,
            "guidance": (
                f"{abundant_desc} "
                "Freely use gpt-6.2-astra (high) for deep verification or gpt-6.2-sol (medium/high) for parallel subtasks."
            ),
        }

    if effective_rem >= 20:
        if (s_ratio is not None and s_ratio >= 1.2) or (p_mins is not None and p_mins <= 90 and (s_rem is None or s_rem >= 25)):
            pacing_parts = []
            if s_ratio is not None:
                pacing_parts.append(f"7d surplus {s_ratio}x")
            if p_mins is not None:
                pacing_parts.append(f"5h resets in {p_mins}m")
            elif s_mins is not None:
                pacing_parts.append(f"7d resets in {round(s_mins / 60, 1)}h")
            pacing_summary = ", ".join(pacing_parts) or "favorable pacing"
            return {
                "tier": "moderate_surplus",
                "strategy": "selective_deep_or_standard",
                "allowDelegation": True,
                "recommendedModel": "gpt-6.2-sol",
                "recommendedReasoningEffort": "high",
                "alternativeModel": "gpt-6.2-astra",
                "alternativeReasoningEffort": "medium",
                "suggestedUseCases": [
                    "Focused codex_review on uncommitted changes (gpt-6.2-sol, high).",
                    "Targeted gpt-6.2-astra (medium) audit on high-risk logic (auth, concurrency, data).",
                    "Generating or verifying edge-case unit tests for modified modules.",
                ],
                "avoidUseCases": ["Unbounded whole-repo sweeps without specific file targets."],
                "pacingMetrics": pacing,
                "guidance": (
                    "Quota is moderate (20-49%), but time-to-reset pacing is favorable "
                    f"({pacing_summary}). "
                    "Use gpt-6.2-sol (high) for focused reviews or gpt-6.2-astra (medium) on critical paths."
                ),
            }
        return {
            "tier": "moderate",
            "strategy": "focused_verification",
            "allowDelegation": True,
            "recommendedModel": "gpt-6.2-sol",
            "recommendedReasoningEffort": "medium",
            "suggestedUseCases": [
                "Single-module codex_review on specific diffs (gpt-6.2-sol, medium).",
                "Focused verification of a concrete bug fix or API contract.",
            ],
            "avoidUseCases": ["High-effort xhigh/max runs or broad multi-agent fan-outs."],
            "pacingMetrics": pacing,
            "guidance": (
                "Quota is moderate (20-49% remaining). Use gpt-6.2-sol (medium) for focused "
                "verification, bug hunting, or single-module tasks."
            ),
        }

    if p_rem is not None and p_rem < 20 and p_mins is not None and p_mins <= 60 and (s_rem is None or s_rem >= 25):
        s_note = f" while 7d quota is healthy ({s_rem}%)" if s_rem is not None else ""
        return {
            "tier": "conserve_5h_short_wait",
            "strategy": "defer_heavy_until_5h_reset",
            "allowDelegation": True,
            "recommendedModel": "gpt-6.2-sol",
            "recommendedReasoningEffort": "low",
            "suggestedUseCases": [
                "Tiny read-only sanity checks now (gpt-6.2-sol, low).",
                f"Defer heavy gpt-6.2-astra reviews until 5h window resets in {p_mins}m.",
            ],
            "avoidUseCases": ["Heavy audits before the imminent 5h reset."],
            "pacingMetrics": pacing,
            "guidance": (
                f"5h quota is low ({p_rem}%), but resets in {p_mins}m{s_note}. "
                "Do only tiny checks now and schedule heavy verification after the 5h reset."
            ),
        }

    return {
        "tier": "conserve",
        "strategy": "high_roi_only",
        "allowDelegation": True,
        "recommendedModel": "gpt-6.2-sol",
        "recommendedReasoningEffort": "low",
        "suggestedUseCases": [
            "Concise, high-ROI sanity checks on critical diffs (gpt-6.2-sol, low).",
            "Targeted question on a specific function or error trace.",
        ],
        "avoidUseCases": ["Broad codebase scans, xhigh/max reasoning, or multi-worker fan-outs."],
        "pacingMetrics": pacing,
        "guidance": (
            "Quota is low (<20% remaining) with significant time until reset. "
            "Restrict Codex to small, targeted read-only checks with gpt-6.2-sol (low)."
        ),
    }


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _fallback_session_rate_limits() -> dict[str, Any] | None:
    pattern = os.path.join(_codex_home(), "sessions", "**", "*.jsonl")
    files = sorted(glob.glob(pattern, recursive=True), key=_safe_mtime, reverse=True)
    for path in files[:5]:
        last_rl = None
        last_ts = None
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"rate_limits"' in line:
                        obj = json.loads(line)
                        rl = obj.get("payload", {}).get("rate_limits")
                        if rl:
                            last_rl = rl
                            last_ts = obj.get("timestamp")
        except Exception:
            continue
        if last_rl:
            mtime = _safe_mtime(path)
            return {
                "source": path,
                "sampledAt": last_ts or (datetime.fromtimestamp(mtime).astimezone().isoformat() if mtime else None),
                "staleMinutes": round(max(0.0, (time.time() - mtime) / 60.0), 1) if mtime else None,
                "rateLimits": last_rl,
            }
    return None


def tool_quota_status(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch live Codex account info, rate limits, reset times, and routing advice."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    try:
        acc_msg, rl_msg = APP_SERVER.call_batch([
            ("account/read", {}),
            ("account/rateLimits/read", {}),
        ], timeout=25.0)
        if "error" in rl_msg:
            raise RuntimeError(f"rateLimits error: {rl_msg['error']}")

        acc = acc_msg.get("result", {}).get("account") if isinstance(acc_msg.get("result"), dict) else None
        rl_res = rl_msg.get("result")
        if not isinstance(rl_res, dict) or not isinstance(rl_res.get("rateLimits"), dict):
            raise RuntimeError("Missing rateLimits object in codex app-server response.")

        rl = rl_res["rateLimits"]
        primary, secondary = _classify_windows(rl.get("primary"), rl.get("secondary"))
        credits = rl.get("credits")
        ordinary_allowed = rl_res.get("ordinaryUsageAllowed")
        is_unlimited = isinstance(credits, dict) and credits.get("unlimited") is True
        is_api_key = isinstance(acc, dict) and acc.get("type") == "apiKey"
        if primary is None and secondary is None and not (is_unlimited or is_api_key or ordinary_allowed is False):
            raise RuntimeError("Both primary and secondary rate-limit windows are missing.")

        return {
            "source": "codex-app-server-live",
            "account": acc,
            "ordinaryUsageAllowed": ordinary_allowed,
            "primary5hWindow": primary,
            "secondary7dWindow": secondary,
            "credits": credits,
            "rateLimitResetCredits": rl_res.get("rateLimitResetCredits"),
            "rateLimitReachedType": rl.get("rateLimitReachedType"),
            "recommendation": _compute_recommendation(
                ordinary_allowed, primary, secondary, credits=credits, account=acc
            ),
        }
    except Exception as exc:
        fallback = _fallback_session_rate_limits()
        if fallback:
            rl = fallback["rateLimits"]
            primary, secondary = _classify_windows(rl.get("primary"), rl.get("secondary"))
            credits = rl.get("credits")
            now_ts = time.time()
            warning = f"Live app-server query failed: {exc}"
            expired_windows = [
                label
                for label, win in (("primary 5h", primary), ("secondary 7d", secondary))
                if win and isinstance(win.get("resetsAtEpoch"), (int, float)) and win["resetsAtEpoch"] <= now_ts
            ]
            if expired_windows:
                warning += (
                    f" Note: fallback {', '.join(expired_windows)} rate-limit window(s) "
                    "already passed their reset timestamp and may be stale."
                )
            return {
                "source": "session-fallback",
                "sessionFile": fallback["source"],
                "sampledAt": fallback["sampledAt"],
                "staleMinutes": fallback["staleMinutes"],
                "warning": warning,
                "primary5hWindow": primary,
                "secondary7dWindow": secondary,
                "credits": credits,
                "recommendation": _compute_recommendation(None, primary, secondary, credits=credits),
            }
        raise


def tool_list_models(args: dict[str, Any]) -> dict[str, Any]:
    """List available Codex GPT models (handling pagination and includeHidden)."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    include_hidden = _as_bool(args.get("include_hidden"), False, "include_hidden")
    try:
        all_models: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"includeHidden": include_hidden}
            if cursor:
                params["cursor"] = cursor
            (msg,) = APP_SERVER.call_batch([("model/list", params)], timeout=25.0)
            if "error" in msg:
                raise RuntimeError(f"model/list error: {msg['error']}")
            result = msg.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise RuntimeError("Missing 'data' list in model/list response.")
            all_models.extend(result["data"])
            cursor = result.get("nextCursor")
            if not cursor:
                break

        if not include_hidden:
            all_models = [m for m in all_models if not m.get("hidden", False)]
        simplified = [
            {
                "id": m.get("id") or m.get("model"),
                "displayName": m.get("displayName"),
                "description": m.get("description"),
                "defaultReasoningEffort": m.get("defaultReasoningEffort"),
                "supportedReasoningEfforts": [
                    e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts", [])
                ],
                "hidden": bool(m.get("hidden", False)),
            }
            for m in all_models
        ]
        return {"source": "codex-app-server-live", "models": simplified}
    except Exception as exc:
        cache_path = os.path.join(_codex_home(), "models_cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    data = json.load(f)
                models = data.get("models", data) if isinstance(data, dict) else data
                if not isinstance(models, list):
                    raise ValueError("Invalid models_cache.json format")
                return {
                    "source": "models_cache.json",
                    "warning": f"Live model/list failed: {exc}",
                    "models": [
                        {
                            "id": m.get("slug") or m.get("id"),
                            "displayName": m.get("display_name"),
                            "description": m.get("description"),
                        }
                        for m in models
                        if isinstance(m, dict) and (include_hidden or m.get("visibility") != "hide")
                    ],
                }
            except Exception:
                pass
        raise


def _git_fingerprint(cwd: str | None) -> dict[str, Any] | None:
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        head = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=3,
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=3,
        )
        h = hashlib.sha256()
        h.update(status.stdout)
        try:
            diff = subprocess.run(
                ["git", "-C", cwd, "diff", "--no-ext-diff"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=2,
            )
            if diff.returncode == 0:
                h.update(b"\x00")
                h.update(diff.stdout)
        except Exception:
            pass
        return {
            "head": _decode_bytes(head.stdout).strip(),
            "statusHash": h.hexdigest(),
        }
    except Exception:
        return None


def _summarize_activity_item(item: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """Extract a compact summary and whether the completed item counts as a tool/action call."""
    itype = item.get("type")
    if itype == "command_execution":
        out = item.get("aggregated_output") or item.get("output") or ""
        if not isinstance(out, str):
            out = str(out)
        entry: dict[str, Any] = {
            "type": "command_execution",
            "command": item.get("command"),
            "exitCode": item.get("exit_code"),
        }
        if out.strip():
            entry["outputTail"] = out.strip()[-800:]
        return entry, True
    if itype == "web_search":
        return {"type": "web_search", "query": item.get("query")}, True
    if itype == "mcp_tool_call":
        return {
            "type": "mcp_tool_call",
            "server": item.get("server"),
            "tool": item.get("tool"),
            "status": item.get("status"),
        }, True
    if itype == "file_change":
        return {"type": "file_change", "changes": item.get("changes")}, True
    if itype == "reasoning":
        text = (item.get("text") or "").strip()
        if text:
            return {"type": "reasoning", "text": text[:500]}, False
    return None, False


def _run_codex_exec(
    cmd: list[str],
    prompt: str | None,
    timeout_seconds: int,
    include_color: bool = True,
    job_record: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    session_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        prefix="codex-last-", suffix=".txt", delete=False
    ) as tmp:
        out_file = tmp.name

    job_obj = _WinJobObject()
    proc: subprocess.Popen[bytes] | None = None
    try:
        full_cmd = [*cmd, "-o", out_file, "--json"]
        if include_color:
            full_cmd.extend(["--color", "never"])
        if prompt is not None:
            full_cmd.append("-")

        _, env = _resolve_codex_command()
        if job_record is not None:
            with JOBS_LOCK:
                if job_record["status"] == "cancelling":
                    return {"exitCode": -2, "cancelled": True, "timedOut": False, "timeoutSeconds": timeout_seconds, "response": ""}

        proc = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=(os.name != "nt"),
        )
        job_obj.assign(proc)

        if job_record is not None:
            with JOBS_LOCK:
                if job_record["status"] == "cancelling":
                    _terminate_process_tree(proc, job_obj)
                    return {"exitCode": -2, "cancelled": True, "timedOut": False, "timeoutSeconds": timeout_seconds, "response": ""}
                job_record["proc"] = proc
                job_record["jobObj"] = job_obj
                job_record["status"] = "running"

        usage = None
        rate_limits = None
        thread_id = None
        agent_messages: list[str] = []
        activity_log: collections.deque[dict[str, Any]] = collections.deque(maxlen=30)
        stderr_chunks: collections.deque[bytes] = collections.deque()
        stderr_bytes = 0
        timed_out = False
        cancelled = False

        def _write_stdin() -> None:
            if prompt is None or proc is None or proc.stdin is None:
                return
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.flush()
            except Exception:
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        def _read_stdout() -> None:
            nonlocal usage, rate_limits, thread_id
            assert proc is not None and proc.stdout is not None
            while True:
                raw = proc.stdout.readline()
                if not raw:
                    break
                line = _decode_bytes(raw).strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev_type = ev.get("type")
                if job_record is not None:
                    with JOBS_LOCK:
                        job_record["lastActivityAt"] = time.time()
                if ev_type == "thread.started" and ev.get("thread_id"):
                    thread_id = ev["thread_id"]
                    if session_meta is not None:
                        with SESSIONS_LOCK:
                            now_ts = time.time()
                            existing = SESSION_BINDINGS.get(thread_id)
                            entry = dict(session_meta)
                            entry["createdAt"] = existing.get("createdAt", now_ts) if existing else now_ts
                            entry["lastUsedAt"] = now_ts
                            SESSION_BINDINGS[thread_id] = entry
                            _prune_sessions_unlocked()
                    if job_record is not None:
                        with JOBS_LOCK:
                            job_record["sessionId"] = thread_id
                elif ev_type == "turn.completed" and "usage" in ev:
                    usage = ev["usage"]
                elif ev_type == "item.completed":
                    item = ev.get("item", {})
                    if item.get("type") == "agent_message" and item.get("text"):
                        agent_messages.append(item["text"])
                        if job_record is not None:
                            with JOBS_LOCK:
                                job_record["agentMessagesCount"] = len(agent_messages)
                                job_record["lastMessagePreview"] = item["text"][:200]
                    else:
                        summary, is_tool = _summarize_activity_item(item)
                        if summary is not None:
                            activity_log.append(summary)
                        if is_tool and job_record is not None:
                            with JOBS_LOCK:
                                job_record["toolCallsCount"] = job_record.get("toolCallsCount", 0) + 1
                elif ev_type == "event_msg":
                    payload = ev.get("payload", {})
                    if payload.get("type") == "token_count":
                        if payload.get("info"):
                            usage = payload["info"].get("last_token_usage") or usage
                        if payload.get("rate_limits"):
                            rate_limits = payload["rate_limits"]

        def _read_stderr() -> None:
            nonlocal stderr_bytes
            assert proc is not None and proc.stderr is not None
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                if len(chunk) >= MAX_STDERR_BYTES:
                    stderr_chunks.clear()
                    stderr_chunks.append(chunk[-MAX_STDERR_BYTES:])
                    stderr_bytes = MAX_STDERR_BYTES
                    continue
                stderr_chunks.append(chunk)
                stderr_bytes += len(chunk)
                while stderr_bytes > MAX_STDERR_BYTES and stderr_chunks:
                    excess = stderr_bytes - MAX_STDERR_BYTES
                    oldest = stderr_chunks[0]
                    if len(oldest) <= excess:
                        stderr_chunks.popleft()
                        stderr_bytes -= len(oldest)
                    else:
                        stderr_chunks[0] = oldest[excess:]
                        stderr_bytes -= excess
                        break

        t_in = threading.Thread(target=_write_stdin, daemon=True)
        t_out = threading.Thread(target=_read_stdout, daemon=True)
        t_err = threading.Thread(target=_read_stderr, daemon=True)
        t_in.start()
        t_out.start()
        t_err.start()

        deadline = (time.monotonic() + timeout_seconds) if timeout_seconds > 0 else None
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if job_record is not None and job_record["status"] == "cancelling":
                cancelled = True
                break
            if deadline is not None:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    timed_out = True
                    break
                time.sleep(min(0.2, rem))
            else:
                time.sleep(0.2)

        if cancelled or timed_out:
            _terminate_process_tree(proc, job_obj)
        else:
            job_obj.close()

        t_in.join(timeout=1.0)
        t_out.join(timeout=2.0)
        t_err.join(timeout=1.0)

        stderr_text = _decode_bytes(b"".join(stderr_chunks)).strip()

        last_message = ""
        if os.path.exists(out_file):
            with open(out_file, "rb") as f:
                last_message = _decode_bytes(f.read()).strip()

        if not last_message and agent_messages:
            last_message = "\n\n".join(agent_messages)

        exit_code = -2 if cancelled else (-1 if timed_out else (proc.returncode if proc.returncode is not None else 1))
        result: dict[str, Any] = {
            "exitCode": exit_code,
            "timedOut": timed_out,
            "cancelled": cancelled,
            "timeoutSeconds": timeout_seconds,
            "response": last_message,
        }
        if thread_id:
            result["sessionId"] = thread_id
        if timed_out or cancelled:
            reason = f"exceeded {timeout_seconds}s and was terminated" if timed_out else "was cancelled"
            resume_hint = (
                f" Session '{thread_id}' is persisted and resumable: call "
                f"codex_exec(session_id='{thread_id}', reasoning_effort='low', "
                "prompt='Do not run any new tools or searches; output all verified findings so far.') "
                "to harvest a complete summary without re-running work."
                if (thread_id and session_meta is not None)
                else ""
            )
            result["warning"] = (
                f"Codex exec {reason}. All captured messages (`agentMessages`) and recent "
                f"tool activity (`activityLog`) are included below.{resume_hint}"
            )
        if (timed_out or cancelled or exit_code != 0) and agent_messages:
            result["agentMessages"] = list(agent_messages)
        if (timed_out or cancelled or exit_code != 0) and activity_log:
            result["activityLog"] = list(activity_log)
        if usage:
            result["usage"] = usage
        if rate_limits:
            result["rateLimits"] = {
                "primary": _format_window(rate_limits.get("primary")),
                "secondary": _format_window(rate_limits.get("secondary")),
            }
        if (timed_out or cancelled or exit_code != 0) and stderr_text:
            result["stderr"] = stderr_text[-3000:]
        return result
    finally:
        if proc is not None and proc.poll() is None:
            _terminate_process_tree(proc, job_obj)
        else:
            job_obj.close()
        try:
            os.remove(out_file)
        except OSError:
            pass


def _prune_finished_jobs_unlocked() -> None:
    now = time.time()
    to_delete: list[str] = []
    finished: list[tuple[float, str]] = []
    for jid, job in JOBS.items():
        if job["status"] in ("completed", "failed", "timed_out", "cancelled"):
            fin = job["finishedAt"] or now
            if now - fin > FINISHED_JOB_TTL_SECONDS:
                to_delete.append(jid)
            else:
                finished.append((fin, jid))
    if len(finished) > MAX_RETAINED_FINISHED_JOBS:
        finished.sort()
        for _, jid in finished[: len(finished) - MAX_RETAINED_FINISHED_JOBS]:
            to_delete.append(jid)
    for jid in to_delete:
        job = JOBS.pop(jid, None)
        if job and job.get("requestId"):
            REQUEST_ID_TO_JOB.pop(job["requestId"], None)


def _launch_background_job(
    kind: str,
    cmd: list[str],
    prompt: str | None,
    timeout_seconds: int,
    include_color: bool,
    meta: dict[str, Any],
    request_id: str | None = None,
    session_id: str | None = None,
    session_meta: dict[str, Any] | None = None,
    start_fingerprint: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    with JOBS_LOCK:
        _prune_finished_jobs_unlocked()
        if request_id and request_id in REQUEST_ID_TO_JOB:
            existing_id = REQUEST_ID_TO_JOB[request_id]
            existing = JOBS.get(existing_id)
            if existing is not None:
                return {
                    **_serialize_job(existing, include_result=(existing["status"] != "running")),
                    "deduplicated": True,
                }
        active_count = sum(1 for j in JOBS.values() if j["status"] in ("queued", "starting", "running", "cancelling"))
        if active_count >= MAX_QUEUED_JOBS:
            raise RuntimeError(
                f"Too many active/queued background jobs ({active_count}/{MAX_QUEUED_JOBS}). "
                "Wait for or cancel existing jobs before submitting more."
            )

        job_id = uuid.uuid4().hex[:12]
        done_event = threading.Event()
        now_ts = time.time()
        job_record: dict[str, Any] = {
            "jobId": job_id,
            "requestId": request_id,
            "kind": kind,
            "status": "queued",
            "startedAt": now_ts,
            "lastActivityAt": now_ts,
            "finishedAt": None,
            "meta": meta,
            "sessionId": session_id,
            "agentMessagesCount": 0,
            "toolCallsCount": 0,
            "lastMessagePreview": None,
            "result": None,
            "error": None,
            "proc": None,
            "jobObj": None,
            "doneEvent": done_event,
        }
        JOBS[job_id] = job_record
        if request_id:
            REQUEST_ID_TO_JOB[request_id] = job_id

    def _worker() -> None:
        acquired = False
        session_lock = None
        session_acquired = False
        try:
            while not JOB_SEMAPHORE.acquire(timeout=0.5):
                with JOBS_LOCK:
                    if job_record["status"] in ("cancelling", "cancelled"):
                        job_record["status"] = "cancelled"
                        if job_record["finishedAt"] is None:
                            job_record["finishedAt"] = time.time()
                        return
            acquired = True
            with JOBS_LOCK:
                if job_record["status"] in ("cancelling", "cancelled"):
                    job_record["status"] = "cancelled"
                    if job_record["finishedAt"] is None:
                        job_record["finishedAt"] = time.time()
                    return
                job_record["status"] = "starting"

            if session_id:
                with SESSIONS_LOCK:
                    session_lock = SESSION_RUN_LOCKS.setdefault(session_id, threading.Lock())
                while not session_lock.acquire(timeout=0.5):
                    with JOBS_LOCK:
                        if job_record["status"] in ("cancelling", "cancelled"):
                            job_record["status"] = "cancelled"
                            if job_record["finishedAt"] is None:
                                job_record["finishedAt"] = time.time()
                            return
                session_acquired = True
                with JOBS_LOCK:
                    if job_record["status"] in ("cancelling", "cancelled"):
                        job_record["status"] = "cancelled"
                        if job_record["finishedAt"] is None:
                            job_record["finishedAt"] = time.time()
                        return

            res = _run_codex_exec(
                cmd,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                include_color=include_color,
                job_record=job_record,
                session_meta=session_meta,
            )
            res.update(meta)
            if start_fingerprint is not None and cwd:
                end_fp = _git_fingerprint(cwd)
                if end_fp and end_fp != start_fingerprint:
                    res["workspaceChangedDuringReview"] = True
                    res["warning"] = (
                        (res.get("warning") + " " if res.get("warning") else "")
                        + "Workspace HEAD or git status changed while background review was running."
                    )

            with JOBS_LOCK:
                if job_record["status"] == "cancelling" or res.get("cancelled"):
                    job_record["status"] = "cancelled"
                elif res.get("timedOut"):
                    job_record["status"] = "timed_out"
                elif res.get("exitCode", 0) != 0:
                    job_record["status"] = "failed"
                else:
                    job_record["status"] = "completed"
                job_record["result"] = res
                job_record["finishedAt"] = time.time()
        except Exception as exc:
            with JOBS_LOCK:
                if job_record["status"] == "cancelling":
                    job_record["status"] = "cancelled"
                else:
                    job_record["status"] = "failed"
                job_record["error"] = str(exc)
                job_record["finishedAt"] = time.time()
        finally:
            if session_acquired and session_lock is not None:
                session_lock.release()
            if acquired:
                JOB_SEMAPHORE.release()
            done_event.set()

    threading.Thread(target=_worker, daemon=True).start()
    return {
        "jobId": job_id,
        "requestId": request_id,
        "status": "queued",
        "kind": kind,
        "timeoutSeconds": timeout_seconds,
        **meta,
        "note": "Job queued/started in background. Poll codex_job_status(job_id=..., wait_seconds=90) or omit job_id with include_results=true to monitor multiple jobs.",
    }


def _serialize_job(job: dict[str, Any], include_result: bool = True) -> dict[str, Any]:
    now = time.time()
    end = job["finishedAt"] or now
    out: dict[str, Any] = {
        "jobId": job["jobId"],
        "kind": job["kind"],
        "status": job["status"],
        "elapsedSeconds": round(end - job["startedAt"], 1),
        "sessionId": job["sessionId"],
        "agentMessagesCount": job["agentMessagesCount"],
        "toolCallsCount": job.get("toolCallsCount", 0),
        **job["meta"],
    }
    if job.get("requestId"):
        out["requestId"] = job["requestId"]
    if job["status"] in ("queued", "starting", "running", "cancelling"):
        last_act = job.get("lastActivityAt") or job["startedAt"]
        out["idleSeconds"] = round(max(0.0, now - last_act), 1)
        if job["lastMessagePreview"]:
            out["lastMessagePreview"] = job["lastMessagePreview"]
    if job["error"]:
        out["error"] = job["error"]
    if include_result and job["result"] is not None:
        out["result"] = job["result"]
    return out


def tool_job_status(args: dict[str, Any], cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """Check status or wait for background Codex job(s)."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    job_id = args.get("job_id")
    wait_seconds = _as_float(args.get("wait_seconds"), 0.0, "wait_seconds", 0.0, 120.0)
    include_results = _as_bool(args.get("include_results"), False, "include_results")

    if job_id is not None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("'job_id' must be a non-empty string.")
        with JOBS_LOCK:
            job = JOBS.get(job_id.strip())
        if not job:
            raise ValueError(f"Unknown job_id: {job_id}")
        deadline = time.monotonic() + wait_seconds
        while wait_seconds > 0 and not job["doneEvent"].is_set():
            if cancel_event is not None and cancel_event.is_set():
                break
            rem = deadline - time.monotonic()
            if rem <= 0:
                break
            job["doneEvent"].wait(timeout=min(0.5, rem))
        with JOBS_LOCK:
            return _serialize_job(job, include_result=True)

    deadline = time.monotonic() + wait_seconds
    while wait_seconds > 0:
        if cancel_event is not None and cancel_event.is_set():
            break
        with JOBS_LOCK:
            active = [j for j in JOBS.values() if not j["doneEvent"].is_set()]
        if not active:
            break
        rem = deadline - time.monotonic()
        if rem <= 0:
            break
        active[0]["doneEvent"].wait(timeout=min(0.5, rem))

    with JOBS_LOCK:
        _prune_finished_jobs_unlocked()
        jobs_list = [_serialize_job(j, include_result=include_results) for j in JOBS.values()]
    with SESSIONS_LOCK:
        sessions_list = [
            {
                "sessionId": sid,
                "cwd": info.get("cwd"),
                "sandbox": info.get("sandbox"),
                "model": info.get("model"),
                **(
                    {"lastUsedAt": formatted_ts}
                    if (formatted_ts := _format_epoch_local(info.get("lastUsedAt"))) is not None
                    else {}
                ),
            }
            for sid, info in sorted(
                SESSION_BINDINGS.items(),
                key=lambda kv: kv[1].get("lastUsedAt", 0.0),
                reverse=True,
            )
        ]
    return {"totalJobs": len(jobs_list), "jobs": jobs_list, "activeSessions": sessions_list}


def tool_job_cancel(args: dict[str, Any]) -> dict[str, Any]:
    """Cancel a running or queued background Codex job (kills full process tree)."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("'job_id' is required and must be a non-empty string.")
    with JOBS_LOCK:
        job = JOBS.get(job_id.strip())
        if not job:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job["doneEvent"].is_set():
            return _serialize_job(job, include_result=True)
        if job["status"] == "queued":
            job["status"] = "cancelled"
            if job["finishedAt"] is None:
                job["finishedAt"] = time.time()
            job["doneEvent"].set()
            return _serialize_job(job, include_result=True)
        job["status"] = "cancelling"
        proc = job.get("proc")
        job_obj = job.get("jobObj")
    if proc is not None:
        _terminate_process_tree(proc, job_obj)
    job["doneEvent"].wait(timeout=5.0)
    with JOBS_LOCK:
        return _serialize_job(job, include_result=True)


def tool_exec(args: dict[str, Any], cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """Run a non-interactive task or verification prompt with a Codex GPT model."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' is required and must be a non-empty string.")

    profile = _validate_profile(args.get("profile"))
    images = _validate_images(args.get("images"))

    model_arg = args.get("model")
    if model_arg is not None:
        if not isinstance(model_arg, str) or not model_arg.strip():
            raise ValueError("'model' must be a non-empty string.")
        model: str | None = model_arg.strip()
    else:
        model = None if profile else "gpt-6.2-sol"

    reasoning_effort = args.get("reasoning_effort")
    if reasoning_effort is not None and reasoning_effort not in VALID_REASONING_EFFORTS:
        raise ValueError(f"'reasoning_effort' must be one of {VALID_REASONING_EFFORTS}.")

    cwd = _validate_cwd(args.get("cwd"), required=False)

    sandbox_arg = args.get("sandbox")
    if sandbox_arg is not None and sandbox_arg not in VALID_SANDBOXES:
        raise ValueError(f"'sandbox' must be one of {VALID_SANDBOXES}.")

    session_id = args.get("session_id")
    if session_id is not None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("'session_id' must be a non-empty string.")
        session_id = session_id.strip()

    background = _as_bool(args.get("background"), False, "background")
    ephemeral = _as_bool(args.get("ephemeral"), False if (session_id or background) else True, "ephemeral")
    skip_git_check = _as_bool(args.get("skip_git_repo_check"), True, "skip_git_repo_check")
    timeout_seconds = _resolve_timeout_seconds(args.get("timeout_seconds"), reasoning_effort)

    request_id = args.get("request_id")
    if request_id is not None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("'request_id' must be a non-empty string.")
        request_id = request_id.strip()

    # Validate session bindings on resume so cwd/sandbox constraints cannot be silently violated
    sandbox = sandbox_arg or "read-only"
    bound_info: dict[str, Any] | None = None
    if session_id:
        with SESSIONS_LOCK:
            bound_info = SESSION_BINDINGS.get(session_id)
        if bound_info is not None:
            if cwd and bound_info.get("cwd") and os.path.normcase(cwd) != os.path.normcase(bound_info["cwd"]):
                raise ValueError(
                    f"Session {session_id} is bound to cwd '{bound_info['cwd']}', cannot resume with '{cwd}'."
                )
            cwd = cwd or bound_info.get("cwd")
            if sandbox_arg is None and bound_info.get("sandbox"):
                sandbox = bound_info["sandbox"]
            elif sandbox == "read-only" and bound_info.get("sandbox") and bound_info["sandbox"] != "read-only":
                raise ValueError(
                    f"Refusing 'read-only' resume on session {session_id} which was created with "
                    f"sandbox '{bound_info['sandbox']}'."
                )
        elif sandbox_arg is None:
            sandbox = "read-only"

    codex_bin, _ = _resolve_codex_command()
    # Parent flags (-C, -s, --color, -p) must precede subcommand (`resume`) if used
    cmd = [codex_bin, "exec"]
    if cwd:
        cmd.extend(["-C", cwd])
    cmd.extend(["-s", sandbox, "--color", "never"])
    if profile:
        cmd.extend(["-p", profile])
    if session_id:
        cmd.append("resume")
        if model:
            cmd.extend(["-m", model])
        if reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        cmd.extend(["-c", f'sandbox_mode="{sandbox}"'])
        for img in images:
            cmd.extend(["-i", img])
        if ephemeral:
            cmd.append("--ephemeral")
        if skip_git_check:
            cmd.append("--skip-git-repo-check")
        cmd.append(session_id)
    else:
        if model:
            cmd.extend(["-m", model])
        if reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        for img in images:
            cmd.extend(["-i", img])
        if ephemeral:
            cmd.append("--ephemeral")
        if skip_git_check:
            cmd.append("--skip-git-repo-check")

    session_meta = None if ephemeral else {"cwd": cwd, "sandbox": sandbox, "model": model}
    meta: dict[str, Any] = {
        "model": model,
        "reasoningEffort": reasoning_effort,
        "requestedSandbox": sandbox,
        "cwd": cwd,
        "resumed": bool(session_id),
        "resumable": not ephemeral,
    }
    if profile:
        meta["profile"] = profile
    if images:
        meta["imagesCount"] = len(images)

    if background:
        return _launch_background_job(
            kind="exec",
            cmd=cmd,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            include_color=False,  # already placed before subcommand
            meta=meta,
            request_id=request_id,
            session_id=session_id,
            session_meta=session_meta,
        )

    session_lock = None
    session_acquired = False
    if session_id:
        with SESSIONS_LOCK:
            session_lock = SESSION_RUN_LOCKS.setdefault(session_id, threading.Lock())
        while not session_lock.acquire(timeout=0.5):
            if cancel_event is not None and cancel_event.is_set():
                return {
                    "exitCode": -2,
                    "cancelled": True,
                    "timedOut": False,
                    "timeoutSeconds": timeout_seconds,
                    "response": "",
                    **meta,
                }
        session_acquired = True
    try:
        res = _run_codex_exec(
            cmd,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            include_color=False,  # already placed before subcommand
            cancel_event=cancel_event,
            session_meta=session_meta,
        )
    finally:
        if session_acquired and session_lock is not None:
            session_lock.release()

    res.update(meta)
    return res


def tool_review(args: dict[str, Any], cancel_event: threading.Event | None = None) -> dict[str, Any]:
    """Run a read-only Codex code review on a git repository."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    cwd = _validate_cwd(args.get("cwd"), required=True)
    assert cwd is not None

    profile = _validate_profile(args.get("profile"))

    model_arg = args.get("model")
    if model_arg is not None:
        if not isinstance(model_arg, str) or not model_arg.strip():
            raise ValueError("'model' must be a non-empty string.")
        model: str | None = model_arg.strip()
    else:
        model = None if profile else "gpt-6.2-sol"

    reasoning_arg = args.get("reasoning_effort")
    if reasoning_arg is not None:
        if reasoning_arg not in VALID_REASONING_EFFORTS:
            raise ValueError(f"'reasoning_effort' must be one of {VALID_REASONING_EFFORTS}.")
        reasoning_effort: str | None = reasoning_arg
    else:
        reasoning_effort = None if profile else "medium"

    base = args.get("base")
    if base is not None and (not isinstance(base, str) or not base.strip()):
        raise ValueError("'base' must be a non-empty branch/ref string.")
    base = base.strip() if isinstance(base, str) else None

    commit = args.get("commit")
    if commit is not None and (not isinstance(commit, str) or not commit.strip()):
        raise ValueError("'commit' must be a non-empty commit SHA/ref string.")
    commit = commit.strip() if isinstance(commit, str) else None

    if base and commit:
        raise ValueError("'base' and 'commit' are mutually exclusive.")

    uncommitted_raw = args.get("uncommitted")
    uncommitted = _as_bool(uncommitted_raw, (base is None and commit is None), "uncommitted")
    if (base or commit) and uncommitted_raw is True:
        raise ValueError("'uncommitted=true' cannot be combined with 'base' or 'commit'.")

    focus = args.get("focus")
    if focus is not None and (not isinstance(focus, str) or not focus.strip()):
        raise ValueError("'focus' must be a non-empty string.")
    focus = focus.strip() if isinstance(focus, str) else None

    if not uncommitted and not base and not commit and not focus:
        raise ValueError("Must specify at least one of 'uncommitted=true', 'base', 'commit', or 'focus'.")

    background = _as_bool(args.get("background"), False, "background")
    timeout_seconds = _resolve_timeout_seconds(args.get("timeout_seconds"), reasoning_effort)

    request_id = args.get("request_id")
    if request_id is not None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("'request_id' must be a non-empty string.")
        request_id = request_id.strip()

    codex_bin, _ = _resolve_codex_command()

    # `codex exec review` forbids combining [PROMPT] (`focus`) with `--uncommitted`/`--base`/`--commit`.
    # When `focus` is combined with a diff scope, route through `codex exec -C <cwd> -s read-only`.
    if focus and (uncommitted or base or commit):
        if base:
            scope_desc = f"changes against base `{base}` (`git diff {base}...HEAD` and `git status`)"
        elif commit:
            scope_desc = f"commit `{commit}` (`git show {commit}`)"
        else:
            scope_desc = "all uncommitted changes (`git status`, `git diff`, and untracked files)"
        review_mode = "focused-readonly-exec"
        cmd = [
            codex_bin, "exec", "-C", cwd, "-s", "read-only", "--color", "never",
        ]
        if profile:
            cmd.extend(["-p", profile])
        if model:
            cmd.extend(["-m", model])
        if reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        cmd.extend(["--ephemeral", "--skip-git-repo-check"])
        prompt: str | None = (
            f"Perform a read-only code review of {scope_desc} in `{cwd}`.\n\n"
            f"Focus instructions:\n{focus}\n\n"
            "Report concrete findings ordered by severity with exact file paths and line numbers."
        )
    else:
        review_mode = "cli-review"
        cmd = [
            codex_bin, "exec", "-C", cwd, "-s", "read-only", "--color", "never",
        ]
        if profile:
            cmd.extend(["-p", profile])
        cmd.append("review")
        if model:
            cmd.extend(["-m", model])
        if reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        cmd.append("--ephemeral")
        if base:
            cmd.extend(["--base", base])
            prompt = None
        elif commit:
            cmd.extend(["--commit", commit])
            prompt = None
        elif uncommitted:
            cmd.append("--uncommitted")
            prompt = None
        else:
            # Pure prompt-only `codex exec review -`
            prompt = focus

    start_fp = _git_fingerprint(cwd)
    meta: dict[str, Any] = {
        "model": model,
        "reasoningEffort": reasoning_effort,
        "cwd": cwd,
        "requestedSandbox": "read-only",
        "reviewMode": review_mode,
    }
    if profile:
        meta["profile"] = profile

    if background:
        return _launch_background_job(
            kind="review",
            cmd=cmd,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            include_color=False,
            meta=meta,
            request_id=request_id,
            start_fingerprint=start_fp,
            cwd=cwd,
        )

    res = _run_codex_exec(
        cmd,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        include_color=False,
        cancel_event=cancel_event,
    )
    if start_fp is not None:
        end_fp = _git_fingerprint(cwd)
        if end_fp and end_fp != start_fp:
            res["workspaceChangedDuringReview"] = True
    res.update(meta)
    return res


TOOLS: list[dict[str, Any]] = [
    {
        "name": "codex_quota_status",
        "description": (
            "Query live OpenAI Codex account quota, 5-hour primary and 7-day secondary "
            "rate-limit usage percentages, exact reset timestamps, and a reset-paced "
            "task-routing recommendation (which GPT model and reasoning effort to use)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "codex_list_models",
        "description": (
            "List available GPT models in the local Codex CLI (e.g. gpt-6.2-sol, "
            "gpt-6.2-astra) along with their supported reasoning efforts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden/internal models (default false).",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "codex_exec",
        "description": (
            "Run a non-interactive prompt via Codex CLI using a chosen GPT model "
            "(e.g. gpt-6.2-sol, gpt-6.2-astra). Use `background: true` for tasks "
            "that may exceed 2-3 minutes, then poll with `codex_job_status`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Task or verification prompt for the Codex GPT model.",
                },
                "model": {
                    "type": "string",
                    "description": "Codex model id, e.g. 'gpt-6.2-sol' or 'gpt-6.2-astra'.",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional Codex config profile (-p / --profile) from $CODEX_HOME.",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": list(VALID_REASONING_EFFORTS),
                    "description": "Reasoning effort override for this run.",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional local image file paths (-i / --image) to attach to the prompt.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for Codex (-C). Validated to exist before running.",
                },
                "sandbox": {
                    "type": "string",
                    "enum": list(VALID_SANDBOXES),
                    "description": "Sandbox policy (default: 'read-only').",
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional sessionId returned by a previous non-ephemeral codex_exec "
                        "call to resume the same Codex conversation with full prior context."
                    ),
                },
                "ephemeral": {
                    "type": "boolean",
                    "description": (
                        "Do not persist session files to disk (default: true for sync new runs, "
                        "false when `background: true` or resuming so interrupted jobs can be resumed)."
                    ),
                },
                "skip_git_repo_check": {
                    "type": "boolean",
                    "description": "Allow running Codex outside a Git repository (default: true).",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Backend execution timeout in seconds (180-3600, or 0 for no hard wall-clock limit; "
                        "omit for defaults: 900s for low/medium, 1800s for high/xhigh/max/ultra). "
                        "Do not pass small values like 30-120s."
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Run asynchronously in the background and return a jobId immediately "
                        "(default: false). Recommended for heavy or parallel analyses."
                    ),
                },
                "request_id": {
                    "type": "string",
                    "description": "Optional idempotency key for background jobs; duplicate calls return the same jobId.",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
    {
        "name": "codex_review",
        "description": (
            "Run a read-only Codex code review on a git repository (`--uncommitted`, `--base`, "
            "`--commit`, or custom `focus`). Use `background: true` for large diffs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {
                    "type": "string",
                    "description": "Absolute path to the git repository root.",
                },
                "model": {
                    "type": "string",
                    "description": "Codex model id (default: 'gpt-6.2-sol' unless 'profile' is set).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional Codex config profile (-p / --profile) from $CODEX_HOME.",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": list(VALID_REASONING_EFFORTS),
                    "description": "Reasoning effort (default: 'medium' unless 'profile' is set).",
                },
                "uncommitted": {
                    "type": "boolean",
                    "description": "Review staged, unstaged, and untracked changes (default: true when base/commit omitted).",
                },
                "base": {
                    "type": "string",
                    "description": "Optional base git branch to diff against instead of uncommitted.",
                },
                "commit": {
                    "type": "string",
                    "description": "Optional commit SHA/ref to review instead of uncommitted/base.",
                },
                "focus": {
                    "type": "string",
                    "description": "Optional custom review instructions or focus areas.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Backend execution timeout in seconds (180-3600, or 0 for no hard wall-clock limit; "
                        "omit for defaults: 900s for low/medium, 1800s for high/xhigh/max/ultra). "
                        "Do not pass small values like 30-120s."
                    ),
                },
                "background": {
                    "type": "boolean",
                    "description": "Run asynchronously in the background and return a jobId immediately (default: false).",
                },
                "request_id": {
                    "type": "string",
                    "description": "Optional idempotency key for background jobs.",
                },
            },
            "required": ["cwd"],
            "additionalProperties": False,
        },
    },
    {
        "name": "codex_job_status",
        "description": (
            "Check progress or collect results of background Codex jobs started with "
            "`background: true`. Pass `job_id` for a single job, or omit `job_id` (with "
            "`include_results: true`) to wait on and inspect all active jobs in one call, plus `activeSessions`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Specific jobId to inspect (omit to wait on and list all background jobs).",
                },
                "wait_seconds": {
                    "type": "number",
                    "description": (
                        "Seconds (0-120) to wait for completion before returning early if done "
                        "(use 30-45 for low/medium, 90-120 for high/xhigh/astra)."
                    ),
                },
                "include_results": {
                    "type": "boolean",
                    "description": "When listing all jobs without job_id, include full results (default: false).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "codex_job_cancel",
        "description": "Cancel a running or queued background Codex job by jobId and terminate its process tree.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The jobId to cancel.",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
]


def _send(obj: dict[str, Any]) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with SEND_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


def _dispatch_tool(name: str, args: dict[str, Any], cancel_event: threading.Event) -> tuple[dict[str, Any], bool]:
    if name == "codex_quota_status":
        return tool_quota_status(args), False
    if name == "codex_list_models":
        return tool_list_models(args), False
    if name == "codex_job_status":
        return tool_job_status(args, cancel_event=cancel_event), False
    if name == "codex_job_cancel":
        return tool_job_cancel(args), False
    if name == "codex_exec":
        res = tool_exec(args, cancel_event=cancel_event)
        is_err = (not args.get("background")) and (res.get("timedOut") or res.get("cancelled") or res.get("exitCode", 0) != 0)
        return res, bool(is_err)
    if name == "codex_review":
        res = tool_review(args, cancel_event=cancel_event)
        is_err = (not args.get("background")) and (res.get("timedOut") or res.get("cancelled") or res.get("exitCode", 0) != 0)
        return res, bool(is_err)
    raise KeyError(f"Unknown tool: {name}")


def _handle_request(msg: dict[str, Any], cancel_event: threading.Event) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        if msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": "params must be an object"}})
        return

    try:
        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            })
            return

        if method == "ping":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            return

        if method == "tools/list":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
            return

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments")
            if args is None:
                args = {}
            if not isinstance(name, str):
                _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": "Tool name must be a string"}})
                return
            try:
                data, is_err = _dispatch_tool(name, args, cancel_event)
                _send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": is_err,
                        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                    },
                })
            except KeyError:
                _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}})
            except Exception as exc:
                _send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                    },
                })
            return

        if msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
    finally:
        if msg_id is not None:
            with CANCEL_LOCK:
                CANCEL_EVENTS.pop(msg_id, None)


def main() -> None:
    _configure_stdio()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})
                continue
            if not isinstance(msg, dict):
                _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: expected JSON object"}})
                continue

            method = msg.get("method")
            msg_id = msg.get("id")

            if method == "notifications/cancelled":
                params = msg.get("params") or {}
                if isinstance(params, dict) and "requestId" in params:
                    target_id = params["requestId"]
                    with CANCEL_LOCK:
                        ev = CANCEL_EVENTS.get(target_id)
                    if ev is not None:
                        ev.set()
                continue

            if method == "notifications/initialized":
                continue

            if msg_id is None:
                continue

            cancel_event = threading.Event()
            with CANCEL_LOCK:
                CANCEL_EVENTS[msg_id] = cancel_event

            if method in ("initialize", "ping", "tools/list"):
                _handle_request(msg, cancel_event)
            else:
                executor.submit(_handle_request, msg, cancel_event)
    finally:
        with CANCEL_LOCK:
            for ev in CANCEL_EVENTS.values():
                ev.set()
        to_terminate: list[tuple[subprocess.Popen[bytes], _WinJobObject | None]] = []
        with JOBS_LOCK:
            for job in list(JOBS.values()):
                if not job["doneEvent"].is_set():
                    job["status"] = "cancelling"
                    proc = job.get("proc")
                    job_obj = job.get("jobObj")
                    if proc is not None:
                        to_terminate.append((proc, job_obj))
        for proc, job_obj in to_terminate:
            _terminate_process_tree(proc, job_obj)
        APP_SERVER.close()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
