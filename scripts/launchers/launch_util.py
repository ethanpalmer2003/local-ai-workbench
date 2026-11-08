"""
- Shared launcher plumbing: process spawning, the Windows kill-on-close job
  object, GPU telemetry triggers, and CLI arg building
"""

import contextlib
import ctypes
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from ctypes import wintypes
from enum import Enum
from typing import Any, cast
from urllib.error import HTTPError, URLError

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.launcher_config import ConsoleTerminalLaunchMode
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.runtime.gpu_memory import get_gpu_memory_snapshot, report_vram_usage_async

# ============================================================
# - Windows Job Object: kill-on-close backstop for SPLIT_DEPENDENT/MERGE launches -
#   every process assigned to it dies the instant the launcher process exits,
#   for ANY reason - normal exit, crash, or the terminal window being closed
#   outright, where our own Python cleanup code never gets a chance to run
# - SPLIT_INDEPENDENT launches skip the job entirely: the process outlives the
#   launcher and every other terminal by design
# - Assigning a process to the job is enough; the OS itself enforces the kill,
#   no cooperation from us required once assigned
# - Child processes spawned by an assigned process (e.g. koboldcpp.exe spawned
#   by the PowerShell tee wrapper) automatically join the same job
# ============================================================

_job_handle = None

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JOB_OBJECT_EXTENDED_LIMIT_INFO = 9
    _PROCESS_JOB_ACCESS = 0x0101  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED = 0x1000
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulong)]
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint]

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
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

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _ensure_job() -> wintypes.HANDLE:
        global _job_handle
        if _job_handle is None:
            job = _kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(
                job, _JOB_OBJECT_EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)
            ):
                error = ctypes.WinError(ctypes.get_last_error())
                _kernel32.CloseHandle(job)
                raise error
            _job_handle = job
        return _job_handle


def assign_process_to_job(pid: int) -> None:
    """
    - Attach pid to the launcher's kill-on-close job object
    - No-op on non-Windows
    - Skip exited PIDs; surface permission and job-assignment failures
    """
    if sys.platform != "win32":
        return
    handle = _kernel32.OpenProcess(_PROCESS_JOB_ACCESS, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists
            return
        raise ctypes.WinError(error)
    try:
        if not _kernel32.AssignProcessToJobObject(_ensure_job(), handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _kernel32.CloseHandle(handle)


def set_console_title(title: str) -> None:
    """Keep a shared-console title stable when child servers change it."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW(title)


def assign_current_process_to_job() -> bool:
    """Best-effort: put the test runner itself in the kill-on-close job.

    A nested/foreign job can reject this; children are still assigned
    individually, so a failed call only loses the race-window protection.
    """
    if sys.platform != "win32":
        return False
    handle = _kernel32.OpenProcess(_PROCESS_JOB_ACCESS, False, os.getpid())
    if not handle:
        return False
    try:
        return bool(_kernel32.AssignProcessToJobObject(_ensure_job(), handle))
    except OSError:
        return False
    finally:
        _kernel32.CloseHandle(handle)


def port_listening(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def prepare_service_port(port: int, title: str) -> None:
    """Apply the configured policy to an occupied port before service startup."""
    if not port_listening(port):
        return
    policy = cfg.LAUNCH.existing_service_policy
    if policy != cfg.ExistingServicePolicy.KILL:
        raise RuntimeError(f"Service port {port} is occupied; existing-service policy is {policy.value}")
    print(f"Stopping existing service on port {port} before starting {title}")
    kill_processes_on_ports(port)
    if port_listening(port):
        raise RuntimeError(f"Could not clear service port {port}; cannot start {title}")


def backend_for_port(port: int) -> str:
    """Which backend answers on this port; KoboldCpp serves no /health, so a wrong guess reads as down."""
    if port in (cfg.SDCPP_SERVICE.port, cfg.SDCPP_SERVICE.internal_port):
        return "sdcpp"
    if port in (cfg.KOBOLDCPP_SERVICE.streaming_ui_port, cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["port"])):
        return "koboldcpp"
    return "llamacpp"


def backend_running(port: int, timeout: float = 2.0, *, backend: str | None = None) -> bool:
    """
    - True if the backend's shared readiness route answers right now.
    - Generic check for any backend (llamacpp 9931, audiocpp 8889, sdcpp 1235,
      koboldcpp 5001 - ports from cfg)
    - Session-locality check for llamacpp: an agent that's still talking while
      this returns False is NOT being served by the local llama-server
    """
    selected = backend or backend_for_port(port)
    try:
        with urllib.request.urlopen(ready_url(selected, port), timeout=timeout):
            return True
    except (URLError, TimeoutError, OSError):
        return False


def llama_server_running(timeout: float = 2.0) -> bool:
    """backend_running(cfg.LLAMACPP_SERVICE.port); kept as the named session-locality check"""
    return backend_running(cfg.LLAMACPP_SERVICE.port, timeout=timeout)


def wait_for_backend(port: int, timeout_s: float, interval_s: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if backend_running(port):
            return True
        time.sleep(interval_s)
    return False


def _pid_alive(pid: int) -> bool:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def process_start_time(pid: int) -> float | None:
    """Wall-clock creation time of pid, or None when it is gone or unreadable."""
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:
        return None


def is_descendant(pid: int, root: int) -> bool:
    """True when pid sits under root; the wrapper's own child is not an escape."""
    try:
        import psutil

        return root in {parent.pid for parent in psutil.Process(pid).parents()}
    except Exception:
        return False


def sweep_escaped_children(ports: int | list[int], since: float | None, root: int | None = None) -> list[int]:
    """Kill listeners on `ports` that started at or after `since`.

    - A descendant launched with CREATE_NEW_CONSOLE escapes `taskkill /T`, so the
      tree kill cannot reach it; the port it holds is the only reliable handle
    - `since` is the create time of the process we just killed: anything older
      predates this run and is left alone, so a user's own server is never taken
    """
    if sys.platform != "win32" or since is None:
        return []
    targets = [ports] if isinstance(ports, int) else list(ports)
    killed: list[int] = []
    for port in targets:
        for pid in listening_process_ids(port):
            started = process_start_time(pid)
            if started is None or started < since - 1.0:
                continue
            kill_process_tree(pid)
            killed.append(pid)
    for pid in killed:
        # - A descendant the tree kill could not reach in time is the normal case for a
        #   console wrapper; only a pid outside the tree is an actual escape
        kind = "stopped remaining child" if root is not None and is_descendant(pid, root) else "swept escaped child"
        print(f"[launcher] {kind} pid {pid} still holding a service port", flush=True)
    return killed


def kill_process_tree(pid: int, ports: int | list[int] | None = None) -> None:
    """
    - Force-kill pid and its full descendant tree
    - Used for explicit shutdown (e.g. Ctrl+C)
    - The Job Object above is the backstop for cases where this code never
      runs at all
    - taskkill reports access denied on stderr while still exiting, so the
      pid is re-read afterwards; a refused kill falls back to a direct
      TerminateProcess instead of leaving an orphan holding the port and VRAM
    - ports: also sweep these service ports for descendants that escaped the
      tree (a CREATE_NEW_CONSOLE child cannot be reached by taskkill /T)
    """
    if sys.platform != "win32":
        return

    started = process_start_time(pid)

    result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True, check=False)
    detail = f"{result.stdout or ''}{result.stderr or ''}".strip()

    if _pid_alive(pid):
        handle = _kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if handle:
            try:
                _kernel32.TerminateProcess(handle, 1)
            finally:
                _kernel32.CloseHandle(handle)

    if ports:
        sweep_escaped_children(ports, started, pid)

    # - an already-dead pid is the normal case for a shutdown path, not a fault
    benign = ("not found", "no running instance", "could not find")
    if _pid_alive(pid):
        print(f"[launcher] WARN: pid {pid} survived taskkill{': ' + detail.splitlines()[-1] if detail else ''}")
    elif result.returncode != 0 and not any(marker in detail.lower() for marker in benign):
        print(f"[launcher] WARN: taskkill could not kill pid {pid}: {detail.splitlines()[-1] if detail else ''}")


def build_cli_args(options: Mapping[str, object]) -> list[str]:
    """
    - Convert {"m": "foo", "steps": 25, "flag": True} into
      ["-m", "foo", "--steps", "25", "--flag"]
    - Single-char keys get "-", longer keys get "--"
    - Keys that already start with "-" (e.g. "-ngl", "--flash-attn") are used
      as-is, unprefixed
    - None values are skipped
    """
    args: list[str] = []
    for key, value in options.items():
        if value is None or value == "":
            continue
        flag = key if key.startswith("-") else ("-" if len(key) == 1 else "--") + key
        if isinstance(value, bool):
            if value:
                args.append(flag)
        else:
            args.append(flag)
            args.append(str(value))
    return args


def prune_stale_temp(max_age_hours: float = 24) -> int:
    """Remove PyInstaller extractions a killed child left behind in the shared temp dir.

    One-file executables extract to `_MEI*` under TEMP and only remove it on a clean
    exit, so a taskkill leaves the whole tree behind. Age-gating keeps a running child safe.
    """
    root = cfg.LAUNCH.temp_dir
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for path in root.glob("_MEI*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _launch_mode(mode: ConsoleTerminalLaunchMode | str | None) -> ConsoleTerminalLaunchMode:
    if mode is None:
        return cfg.LAUNCH.console_terminal_mode
    return mode if isinstance(mode, ConsoleTerminalLaunchMode) else ConsoleTerminalLaunchMode(mode)


def _clear_requested_ports(kill_ports: int | list[int] | None, title: str) -> None:
    if not kill_ports:
        return
    for port in [kill_ports] if isinstance(kill_ports, int) else kill_ports:
        prepare_service_port(port, title)


def _child_environment(env: Mapping[str, str | None] | None) -> dict[str, str]:
    """Caller overrides (None unsets) plus a project-local TEMP/TMP/TMPDIR."""
    child_env = os.environ.copy()
    for key, value in (env or {}).items():
        if value is None:
            child_env.pop(key, None)
        else:
            child_env[key] = value
    for name in ("TEMP", "TMP", "TMPDIR"):
        child_env[name] = str(cfg.LAUNCH.temp_dir)
    return child_env


def _powershell_launch_cmd(cmd: list[str], title: str, log_file: str | None) -> list[str]:
    quoted = " ".join("'" + part.replace("'", "''") + "'" for part in cmd)
    title_literal = "'" + title.replace("'", "''") + "'"
    ps_command = f"$Host.UI.RawUI.WindowTitle = {title_literal}; & {quoted}"
    if log_file:
        log_literal = "'" + log_file.replace("'", "''") + "'"
        ps_command += f" 2>&1 | Tee-Object -FilePath {log_literal}"
    return ["powershell.exe", "-NoProfile", "-NoExit", "-Command", ps_command]


def _merge_streams(mode: ConsoleTerminalLaunchMode, capture: Any) -> tuple[Any, Any]:
    """MERGE runs headless; an opened log_file replaces the inherited console."""
    if mode != ConsoleTerminalLaunchMode.MERGE:
        return None, None
    if capture is None:
        return sys.stdout, sys.stderr
    return capture, capture


def _bind_job(proc: subprocess.Popen[Any], mode: ConsoleTerminalLaunchMode) -> None:
    # - SPLIT_INDEPENDENT: no job object - the process outlives this launcher and
    #   every other terminal by design
    if mode == ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT:
        return
    try:
        assign_process_to_job(proc.pid)
    except OSError:
        kill_process_tree(proc.pid)
        proc.wait(timeout=10)
        raise


def launch_process(
    cmd: list[str],
    title: str,
    cwd: str | None = None,
    kill_ports: int | list[int] | None = None,
    report_vram: bool = False,
    extra_args: list[str] | None = None,
    mode: ConsoleTerminalLaunchMode | str | None = None,
    log_file: str | None = None,
    env: Mapping[str, str | None] | None = None,
    bind_job: bool = False,
) -> subprocess.Popen[Any]:
    """
    - kill_ports: service ports are prepared according to the configured
      existing-service policy before the new process starts
    - log_file: capture stdout+stderr directly in MERGE mode; other Windows
      modes mirror them through PowerShell Tee-Object in their own window
    - the child's TEMP/TMP/TMPDIR point inside the project, so a sandboxed
      shell that denies the system temp directory cannot abort the child
    - bind_job: an owned launch joins the launcher's kill-on-close job even in
      SPLIT_INDEPENDENT, so a descendant spawned after the kill snapshot cannot
      escape; leave it off for services the user starts and expects to outlive
      the launcher
    """
    resolved = _launch_mode(mode)
    full_cmd = [*cmd, *(extra_args or [])]
    _clear_requested_ports(kill_ports, title)

    vram_before = get_gpu_memory_snapshot() if report_vram else None
    new_console = sys.platform == "win32" and resolved != ConsoleTerminalLaunchMode.MERGE

    cfg.LAUNCH.temp_dir.mkdir(parents=True, exist_ok=True)
    prune_stale_temp()

    launch_cmd = _powershell_launch_cmd(full_cmd, title, log_file) if new_console else full_cmd
    child_env = _child_environment(env)

    with contextlib.ExitStack() as stack:
        capture = None
        if resolved == ConsoleTerminalLaunchMode.MERGE and log_file:
            capture = stack.enter_context(open(log_file, "w", encoding="utf-8"))
        output, error_output = _merge_streams(resolved, capture)
        proc = subprocess.Popen(
            launch_cmd,
            cwd=cwd,
            env=child_env,
            stdout=output,
            stderr=error_output,
            creationflags=subprocess.CREATE_NEW_CONSOLE if new_console else 0,
        )

    _bind_job(proc, resolved)
    if bind_job and resolved == ConsoleTerminalLaunchMode.SPLIT_INDEPENDENT:
        try:
            assign_process_to_job(proc.pid)
        except OSError:
            kill_process_tree(proc.pid)
            proc.wait(timeout=10)
            raise
    if report_vram:
        report_vram_usage_async(title, proc.pid, vram_before, log_file=log_file)
    return proc


def launch_module(
    module: str, title: str, mode: ConsoleTerminalLaunchMode | None = None, extra_args: list[str] | None = None
) -> subprocess.Popen[Any]:
    return launch_process(
        [sys.executable, "-m", module], title=title, cwd=str(project_cfg.BASE_DIR), mode=mode, extra_args=extra_args
    )


def _listening_pids(targets: set[str]) -> list[tuple[str, str]]:
    """(port, pid) for every listener netstat reports on one of `targets`"""
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=False)
    return [
        (line.split()[1].rsplit(":", 1)[-1], line.split()[-1])
        for line in result.stdout.splitlines()
        if "LISTENING" in line and len(line.split()) >= 5 and line.split()[1].rsplit(":", 1)[-1] in targets
    ]


def listening_process_ids(port: int) -> list[int]:
    return sorted({int(pid) for _, pid in _listening_pids({str(port)})})


def kill_processes_on_ports(ports: int | list[int]) -> None:
    if sys.platform != "win32":
        return

    targets = {str(port) for port in ([ports] if isinstance(ports, int) else ports)}

    for pid in {pid for _, pid in _listening_pids(targets)}:
        _ = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, check=False)
        if _pid_alive(int(pid)):
            handle = _kernel32.OpenProcess(_PROCESS_TERMINATE, False, int(pid))
            if handle:
                try:
                    _kernel32.TerminateProcess(handle, 1)
                finally:
                    _kernel32.CloseHandle(handle)

    # - taskkill reports access denied on stderr while still exiting for the
    #   caller, so the port has to be re-read: claiming a clear that did not
    #   happen sends the next launch into a silent port share
    still = {port for port, _ in _listening_pids(targets)}
    for port in sorted(targets):
        if port in still:
            print(f"[launcher] WARN: port {port} still listening after kill (access denied?)", flush=True)
        else:
            print(f"[launcher] cleared port {port}", flush=True)


def describe_process(pid: int) -> str:
    """Human-readable owner for a pid, used when refusing to touch a listener."""
    try:
        import psutil

        info = psutil.Process(int(pid)).as_dict(attrs=["name", "exe", "cmdline"], ad_value=None)
    except Exception:
        return "unknown owner"
    name = info.get("name") or info.get("exe") or "unknown"
    cmdline = " ".join(info.get("cmdline") or [])[:200]
    return f"{name} | {info.get('exe')} | {cmdline}"


def kill_owned_processes_on_ports(ports: int | list[int], owned_pids: set[int] | list[int]) -> None:
    """Stop listeners only when this run spawned them; refuse unowned ones.

    Tests must never taskkill a server the user started (for example a Pi or
    Strata session). Unknown listeners are left running and reported.
    """
    if sys.platform != "win32":
        return
    owned = {int(pid) for pid in owned_pids}
    targets = [ports] if isinstance(ports, int) else list(ports)
    refused: list[str] = []
    for port in targets:
        for pid in listening_process_ids(port):
            if pid in owned:
                kill_process_tree(pid, ports=port)
            else:
                refused.append(f"port {port} pid {pid} ({describe_process(pid)})")
    if refused:
        raise RuntimeError("Refusing to stop unowned listeners: " + "; ".join(refused))


def wait_for_exit(proc: subprocess.Popen[Any]) -> None:
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[launcher] interrupted, terminating...")
        proc.terminate()


def print_ready(tag: str, port: int | str, args: list[str] | None = None, **config: object) -> None:
    """
    - Standard startup line: port, full CLI command, and config details
    - args: the exact command being spawned (exe + all CLI args)
    """
    print(f"[{tag}] running on port {port}")
    if args:
        print(f"[{tag}] args: {' '.join(args)}")
    if config:
        details = ", ".join(f"{k}={v}" for k, v in config.items())
        print(f"[{tag}] config: {details}")


def _format_setting(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return repr(sorted(map(str, value)))
    return repr(value)


def print_settings(tag: str, label: str, settings: Any, off: bool = False) -> None:
    """
    - Dump a settings dataclass at startup
    - 'label: off' when disabled, otherwise every field as key=value
    """
    if off:
        print(f"[{tag}] {label}: off")
        return
    values = (
        settings.items()
        if isinstance(settings, Mapping)
        else ((field.name, getattr(settings, field.name)) for field in dataclasses.fields(settings))
    )
    fields = ", ".join(f"{name}={_format_setting(value)}" for name, value in values)
    print(f"[{tag}] {label}: {fields}")


def backend_unavailable(error: BaseException) -> bool:
    if isinstance(error, HTTPError):
        return error.code in (502, 503)
    reason = error.reason if isinstance(error, URLError) else error
    return isinstance(reason, (ConnectionRefusedError, TimeoutError))


def backend_ready(url: str, timeout: float = 2) -> bool:
    """Quiet readiness probe; unexpected HTTP, socket and programming errors propagate."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
        return True
    except (URLError, ConnectionRefusedError, TimeoutError) as error:
        if not backend_unavailable(error):
            raise
        return False


def trigger_preload(
    enabled: bool,
    tag: str,
    url: str,
    payload: dict[str, object],
    on_success: Callable[[], None] | None = None,
    background: bool = True,
    ready_url: str | None = None,
) -> None:
    if not enabled:
        return

    def _preload_task():
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        for _ in range(cfg.LAUNCH.warmup_policy.attempts):
            try:
                if ready_url and not backend_ready(ready_url, cfg.LAUNCH.warmup_policy.request_timeout_s):
                    time.sleep(cfg.LAUNCH.warmup_policy.retry_interval_s)
                    continue
                with urllib.request.urlopen(req, timeout=cfg.LAUNCH.warmup_policy.request_timeout_s) as response:
                    while response.read(65536):
                        pass
            except (URLError, ConnectionRefusedError, TimeoutError) as error:
                if not backend_unavailable(error):
                    raise
                time.sleep(cfg.LAUNCH.warmup_policy.retry_interval_s)
                continue
            if on_success:
                on_success()
            print(f"[{tag}] Warmup complete")
            break
        else:
            raise TimeoutError(f"[{tag}] Warmup failed after {cfg.LAUNCH.warmup_policy.attempts} attempts")

    if background:
        threading.Thread(target=_preload_task, daemon=True).start()
    else:
        _preload_task()
