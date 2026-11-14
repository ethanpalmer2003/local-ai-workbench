"""Shared benchmark backend ownership; healthy instances are reused and never stopped here."""

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

from scripts.benchmarks.shared.paths import RunPaths
from scripts.benchmarks.shared.vram import BenchmarkVram
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.shared.wait import http_ready, wait_ready

NATIVE_BACKENDS = {"kobold": "koboldcpp", "image": "sdcpp", "audio": "audiocpp"}


def kobold_port() -> int:
    value = cfg.KOBOLDCPP_KCPPS_ARGS["port"]
    if not isinstance(value, int):
        raise TypeError("Kobold port must be an integer")
    return value


def listening(port: int) -> bool:
    return launch_util.port_listening(port)


def ports(backend: str) -> tuple[int, ...]:
    if backend not in ("kobold", "audio", "image"):
        raise ValueError(f"Unknown benchmark backend: {backend}")
    if backend == "kobold":
        return (kobold_port(),)
    service = cfg.AUDIOCPP_SERVICE if backend == "audio" else cfg.SDCPP_SERVICE
    return service.port, service.internal_port


def require_free(backend: str) -> None:
    occupied = [port for port in ports(backend) if listening(port)]
    if occupied:
        raise RuntimeError(f"{backend} ports already occupied: {occupied}; existing services will not be replaced")


def worker(backend: str, usage_profile: str = "standalone", llm: str = "kobold") -> None:
    from scripts.launchers.audiocpp import audiocpp_proxy
    from scripts.launchers.koboldcpp import kobold
    from scripts.launchers.sdcpp import proxy as sdcpp_proxy

    require_free(backend)
    cfg.LAUNCH.console_terminal_mode = cfg.ConsoleTerminalLaunchMode.MERGE
    # Explicit measured requests replace automatic warmups in this probe only.
    cfg.AUDIOCPP_SERVICE.warmup = False
    cfg.SDCPP_SERVICE.warmup = False
    if backend in ("audio", "image") and usage_profile == "shared":
        sys.argv = [sys.argv[0], "--usage-profile", "shared"]
    if backend == "audio":
        audiocpp_proxy.main()
    elif backend == "image":
        sdcpp_proxy.main()
    else:
        from scripts.launchers.koboldcpp import external_llm

        kobold.LOG_DIR.mkdir(parents=True, exist_ok=True)
        if llm == "external":
            external_llm.start(kobold.LOG_DIR / "llamacpp_external_probe.log")
        process = launch_util.launch_process(
            kobold.server_command(usage_profile, no_model=llm == "external"),
            title="Kobold VRAM probe",
            cwd=str(project_cfg.SCRIPTS_DIR),
            mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        )
        process.wait()
        if process.returncode:
            raise RuntimeError(f"Kobold exited with {process.returncode}")


def start(
    backend: str,
    paths: RunPaths,
    owned: list[subprocess.Popen[Any]],
    usage_profile: str = "standalone",
    llm: str = "kobold",
) -> None:
    require_free(backend)
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.update(
        PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", AI_LOGS_DIR=str(paths.logs), AI_OUTPUT_DIR=str(paths.artifacts)
    )
    with (paths.logs / f"{backend}.log").open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scripts.shared.backends",
                "--worker",
                backend,
                "--usage-profile",
                usage_profile,
                "--llm",
                llm,
            ],
            cwd=project_cfg.BASE_DIR,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    owned.append(process)
    launch_util.assign_process_to_job(process.pid)
    url = ready_url(NATIVE_BACKENDS[backend], ports(backend)[0])
    wait_ready(
        lambda: http_ready(url, strict=True),
        90,
        label=f"{backend} (log: {paths.logs / (backend + '.log')})",
        process=process,
        interval=0.5,
    )
    print(f"[READY] {backend}, pid {process.pid}", flush=True)


@contextmanager
def backend_sessions(run: RunPaths, backends: tuple[str, ...], start_missing: bool = True):
    context = dict(require_native_execution("Live backend benchmark"))
    with BenchmarkVram(run, context) as memory, owned_backend_sessions(run, backends, start_missing):
        for backend in backends:
            memory.watch_backend(backend, launch_util.listening_process_ids(ports(backend)[0]))
        memory.stage = "ready"
        try:
            yield memory
        finally:
            memory.stage = "cleanup"


@contextmanager
def owned_backend_sessions(run: RunPaths, backends: tuple[str, ...], start_missing: bool):
    """Lifecycle primitive for probes that supply their own mandatory resource monitor."""
    owned: list[subprocess.Popen[Any]] = []
    try:
        missing = []
        for backend in backends:
            url = ready_url(NATIVE_BACKENDS[backend], ports(backend)[0])
            if http_ready(url, strict=True):
                print(f"[REUSE] {backend}", flush=True)
            else:
                missing.append(backend)
        if missing and not start_missing:
            raise RuntimeError(f"Missing/unhealthy backends: {missing}; automatic startup is disabled")
        # - Refuse occupied unhealthy services before starting anything; never clear user ports.
        for backend in missing:
            require_free(backend)
        if "kobold" in missing and launch_util.llama_server_running():
            raise RuntimeError("Local llama-server is active; confirm session safety before starting Kobold")
        with ThreadPoolExecutor(max_workers=max(1, len(missing))) as pool:
            futures = [pool.submit(start, backend, run, owned) for backend in missing]
            for future in futures:
                future.result()
        yield
    finally:
        for process in reversed(owned):
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
                process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("kobold", "audio", "image"), required=True)
    parser.add_argument("--usage-profile", choices=("standalone", "shared"), default="standalone")
    parser.add_argument("--llm", choices=("kobold", "external"), default="kobold")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]
    worker(args.worker, args.usage_profile, args.llm)


if __name__ == "__main__":
    main()
