"""Keep full-GPU Kobold resident while swapping Breeze and the Nova server."""

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

from scripts.benchmarks.koboldcpp.kobold_stack_vram import generate
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.tests.shared import backends
from scripts.tests.shared import benchmark_config as benchmark_cfg
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.resources import summarize_resources, watch_resources

SPEECH = "The path is quiet. Stay close while I check the entrance."
RUN_SECONDS = 600


class SwapProbe:
    def __init__(self, paths: RunPaths, context: dict[str, Any]):
        self.paths = paths
        self.started = time.monotonic()
        self.stop = Event()
        self.owned: list[subprocess.Popen[Any]] = []
        self.active: dict[str, subprocess.Popen[Any]] = {}
        self.watchers: list[Thread] = []
        self.samples: dict[str, list[dict[str, Any]]] = {}
        self.memory = GpuMemoryMonitor(None, paths.logs / "vram.jsonl", fast_windows=True)
        self.report: dict[str, Any] = {
            "name": "Kobold resident / Breeze-Nova swap",
            "category": "probes",
            "status": "running",
            "execution_context": context,
            "guards": {
                "minimum_free_ram_gib": benchmark_cfg.MINIMUM_FREE_RAM_GIB,
                "whole_run_seconds": RUN_SECONDS,
                "request_seconds": 90,
            },
            "events": [],
            "settings": {
                "kobold_model": cfg.KOBOLDCPP_SERVICE.model,
                "kobold_usage_profile": "standalone",
                "audio_model": cfg.AUDIOCPP_SERVICE.model,
                "image_model": cfg.SDCPP_SERVICE.model,
                "image_args": shared_gpu.IMAGE_ARGS,
                "speech_text": SPEECH,
                "swap_method": "stop/restart owned native server and proxy worker; no model downloads",
                "limits": "Explicit prototype transitions, not yet automatic production request routing; OS caches not reset; whole-adapter VRAM includes other apps",
            },
        }
        self.save()

    def save(self) -> None:
        self.report["total_seconds"] = time.monotonic() - self.started
        self.paths.write_report(self.report)

    def record(self, label: str, action):
        self.memory.stage = label
        started = time.monotonic()
        try:
            return action()
        finally:
            event = {
                "action": label,
                "seconds": time.monotonic() - started,
                "elapsed_seconds": time.monotonic() - self.started,
            }
            self.report["events"].append(event)
            self.save()
            print("[TIMING] " + json.dumps(event), flush=True)

    def start_backend(self, backend: str, label: str) -> None:
        import psutil

        if backend in self.active:
            raise RuntimeError(f"{backend} already active")
        folder = RunPaths(self.paths.root / label)
        folder.create()
        profile = "shared" if backend == "image" else "standalone"
        self.record(label, lambda: backends.start(backend, folder, self.owned, usage_profile=profile))
        process = self.owned[-1]
        self.active[backend] = process
        pid = launch_util.listening_process_ids(backends.ports(backend)[-1])[0]
        self.report.setdefault("native_pids", {})[label] = pid
        target = SimpleNamespace(pid=pid, poll=lambda: None if psutil.pid_exists(pid) else 0)
        samples: list[dict[str, Any]] = []
        self.samples[label] = samples
        watcher = Thread(
            target=watch_resources,
            args=(target, self.stop, samples, self.started + RUN_SECONDS, lambda: self.memory.stage, self.started),
            daemon=True,
        )
        self.watchers.append(watcher)
        watcher.start()
        self.save()

    def stop_backend(self, backend: str, label: str) -> None:
        process = self.active.pop(backend)

        def stop():
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
                process.wait(timeout=10)
            deadline = time.monotonic() + 10
            while any(backends.listening(port) for port in backends.ports(backend)):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{backend} owned ports did not close")
                time.sleep(0.1)

        self.record(label, stop)
        self.memory.stage = label + "-vram-settle"
        time.sleep(2)

    def guard(self) -> None:
        import psutil

        floor = self.report["guards"]["minimum_free_ram_gib"]
        while not self.stop.wait(0.5):
            if time.monotonic() > self.started + RUN_SECONDS or psutil.virtual_memory().available < floor * 2**30:
                self.report["guard_abort"] = "Free-RAM floor or whole-run deadline reached"
                for process in reversed(self.owned):
                    if process.poll() is None:
                        launch_util.kill_process_tree(process.pid)
                return

    def speech(self, label: str) -> None:
        self.record(label, lambda: generate("audio", self.paths, label, SPEECH))

    def parallel_conversation(self, label: str) -> None:
        self.memory.stage = label
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(generate, kind, self.paths, label, SPEECH) for kind in ("text", "audio")]
            for job in jobs:
                job.result()

    def run(self, cycles: int) -> None:  # noqa: C901
        try:
            Thread(target=self.guard, daemon=True).start()
            with self.memory:
                self.memory.stage = "desktop-baseline"
                time.sleep(3)
                self.start_backend("kobold", "kobold-start")
                kobold_pid = self.report["native_pids"]["kobold-start"]
                self.start_backend("audio", "audio-initial-start")
                self.speech("audio-initial-first")
                self.speech("audio-initial-warm")
                self.parallel_conversation("conversation-before")
                for cycle in range(1, cycles + 1):
                    self.stop_backend("audio", f"cycle-{cycle}-audio-stop")
                    self.start_backend("image", f"cycle-{cycle}-image-start")
                    for image in (1, 2):
                        label = f"cycle-{cycle}-image-{image}"
                        self.record(label, lambda: generate("image", self.paths, label))
                    self.stop_backend("image", f"cycle-{cycle}-image-stop")
                    self.start_backend("audio", f"cycle-{cycle}-audio-start")
                    self.speech(f"cycle-{cycle}-audio-first")
                    self.speech(f"cycle-{cycle}-audio-warm")
                    if launch_util.listening_process_ids(backends.ports("kobold")[0]) != [kobold_pid]:
                        raise RuntimeError("Kobold PID changed during the swap")
                self.parallel_conversation("conversation-after")
                if self.report.get("guard_abort") or any(
                    row.get("abort") for rows in self.samples.values() for row in rows
                ):
                    raise RuntimeError("Resource guard triggered")
                self.report["status"] = "passed"
        except BaseException as error:
            self.report.update(status="failed", error=str(error))
            raise
        finally:
            self.stop.set()
            for process in reversed(self.owned):
                if process.poll() is None:
                    launch_util.kill_process_tree(process.pid)
                    process.wait(timeout=10)
            for watcher in self.watchers:
                watcher.join(timeout=3)
            self.report["resources"] = {name: summarize_resources(rows) for name, rows in self.samples.items()}
            (self.paths.logs / "resources.json").write_text(json.dumps(self.samples, indent=2) + "\n")
            (self.paths.artifacts / "vram.json").write_text(json.dumps(self.memory.summary(), indent=2) + "\n")
            deadline = time.monotonic() + 5
            while any(
                backends.listening(port) for name in ("kobold", "audio", "image") for port in backends.ports(name)
            ):
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
            self.report["remaining_ports"] = {
                name: [port for port in backends.ports(name) if backends.listening(port)]
                for name in ("kobold", "audio", "image")
            }
            self.save()
            print(
                json.dumps({key: self.report.get(key) for key in ("status", "error", "guards", "remaining_ports")}),
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    context = dict(require_native_execution("Kobold / TTS / image swap benchmark"))
    if launch_util.llama_server_running():
        raise RuntimeError("An existing llama-server is active; no server was stopped")
    for backend in ("kobold", "audio", "image"):
        backends.require_free(backend)
    paths = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {paths.root}", flush=True)
    SwapProbe(paths, context).run(args.cycles)


if __name__ == "__main__":
    main()
