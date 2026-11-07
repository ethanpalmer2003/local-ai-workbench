"""Shared llama.cpp benchmark trial: free-session guard, speculative config and server lifetime.

- The speculation runners (benchmark_ngram, benchmark_speedbench, benchmark_specspeed)
  repeat this block verbatim; keeping it here is the single owner.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import wait_ready
from scripts.benchmarks.shared.reporting import BENCHMARK_REASONING_EFFORT
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


def require_free_session(message: str = "Stop the existing llama-server before running the comparison") -> None:
    if launch_util.llama_server_running():
        raise RuntimeError(message)


def speculation_config(conf: LlamaConfig, options: dict[str, str]) -> LlamaConfig:
    """A trial LlamaConfig whose profile extra_args are the base profile plus the candidate options."""
    trial = LlamaConfig(ini_overrides={**options, "fit": "off", "reasoning-effort": BENCHMARK_REASONING_EFFORT})
    trial.profile = replace(conf.profile, extra_args={**conf.profile.extra_args, **options})
    return trial


@contextmanager
def running_server(
    trial: LlamaConfig,
    log: Path,
    *,
    title: str,
    guard: bool = True,
    alias: str | None = None,
    ready_timeout: float | None = None,
) -> Iterator[tuple[str, list[str], subprocess.Popen[bytes]]]:
    """Launch one llama.cpp server, wait for readiness, and always tear it down.

    Yields (base_url, command, process). `guard` refuses an occupied test session; `alias`
    rewrites the --alias argument; the process tree is killed even on failure.
    """
    command = trial.build_cmd(log)
    if alias is not None:
        command[command.index("--alias") + 1] = alias
    if guard and (launch_util.llama_server_running() or launch_util.port_listening(trial.port)):
        raise RuntimeError("Existing llama.cpp session retained; benchmark requires a free test session")
    process = launch_util.launch_process(
        command,
        title=title,
        cwd=str(trial.build_dir),
        kill_ports=trial.port,
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log),
    )
    try:
        base = f"http://127.0.0.1:{trial.port}"
        wait_ready(base, process, ready_timeout or cfg.LLAMACPP_SERVICE.ready_timeout_s)
        yield base, command, process
    finally:
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
        process.wait(timeout=15)
