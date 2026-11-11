"""Exercise actual proxy-driven native model swapping with all server PIDs retained."""

import contextlib
import faulthandler
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event, Thread
from typing import Any

from scripts.benchmarks.koboldcpp.kobold_stack_vram import generate
from scripts.config.shared import image_on_demand as demand_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.runtime import image_on_demand as demand
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.runtime.gpu_memory import GpuMemoryMonitor
from scripts.tests.cases.koboldcpp.kobold_image_swap import SPEECH
from scripts.tests.shared import backends
from scripts.tests.shared import benchmark_config as benchmark_cfg
from scripts.tests.shared.http_server import request
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.resources import summarize_resources, watch_resources

RUN_SECONDS = 600


class NativeSessionProbe:
    def __init__(self, controls_only: bool = False):
        context = dict(require_native_execution("Native image-session integration benchmark"))
        self.paths = CasePaths(__file__).new_run()
        print(f"[OUTPUT] {self.paths.root}", flush=True)
        kobold.LOG_DIR = self.paths.logs
        cfg.AUDIOCPP_SERVICE.warmup = False
        cfg.SDCPP_SERVICE.warmup = False
        self.pipeline = demand.ImageSessionPipeline(lambda: kobold.start_kobold("standalone")[0], self.paths.logs)
        self.memory = GpuMemoryMonitor(None, self.paths.logs / "vram.jsonl", fast_windows=True)
        self.started, self.stop = time.monotonic(), Event()
        self.samples: dict[str, list[dict[str, Any]]] = {}
        self.watchers: list[Thread] = []
        self.report: dict[str, Any] = {
            "name": "Native proxy-driven image sessions",
            "category": "probes",
            "status": "running",
            "execution_context": context,
            "guards": {
                "minimum_free_ram_gib": benchmark_cfg.MINIMUM_FREE_RAM_GIB,
                "whole_run_seconds": RUN_SECONDS,
                "request_seconds": 90,
            },
            "settings": {
                "model_method": "native HTTP load/unload; no restart during mode changes",
                "kobold_command": kobold.server_command("standalone"),
                "audio_model": self.pipeline.native.audio_model,
                "image_profile": cfg.SDCPP_SERVICE.model,
                "image_args": shared_gpu.IMAGE_ARGS,
                "native_management": asdict(demand_cfg.SETTINGS),
                "speech": SPEECH,
            },
        }
        self.controls_only = controls_only
        self.report["scenario"] = "native-controls-and-recovery" if controls_only else "two-image-sessions"

    def owned(self):
        return [
            *self.pipeline.native.processes,
            *([self.pipeline.kobold_process] if self.pipeline.kobold_process is not None else []),
        ]

    def guard(self):
        import psutil

        while not self.stop.wait(0.5):
            if (
                time.monotonic() > self.started + RUN_SECONDS
                or psutil.virtual_memory().available < self.report["guards"]["minimum_free_ram_gib"] * 2**30
            ):
                self.report["guard_abort"] = "Free RAM floor or whole-run deadline reached"
                self.pipeline.coordinator.close()
                for process in self.owned():
                    if process.poll() is None:
                        demand.launch_util.kill_process_tree(process.pid)

    def save(self):
        self.report["total_seconds"] = time.monotonic() - self.started
        self.report["transitions"] = self.pipeline.native.events
        self.report["native_calls"] = self.pipeline.native.calls
        self.report["native_fault_restarts"] = self.pipeline.native.restarts
        self.paths.write_report(self.report)

    def generate_one(self, kind: str, label: str):
        self.memory.stage = label
        result = generate(kind, self.paths, label, SPEECH, text_port=cfg.KOBOLDCPP_SERVICE.streaming_ui_port)
        self.save()
        print(f"[DONE] {label}", flush=True)
        return result

    def check_pids(self):
        current = [process.pid for process in self.owned()]
        if current != self.report["native_pids"] or any(process.poll() is not None for process in self.owned()):
            raise RuntimeError("Native server PID changed or exited during the swap")

    def watch_processes(self):
        for index, process in enumerate(self.owned()):
            rows: list[dict[str, Any]] = []
            self.samples[str(index)] = rows
            watcher = Thread(
                target=watch_resources,
                args=(process, self.stop, rows, self.started + RUN_SECONDS, lambda: self.memory.stage, self.started),
                daemon=True,
            )
            self.watchers.append(watcher)
            watcher.start()

    def two_sessions(self):
        self.generate_one("audio", "initial-speech")
        self.generate_one("audio", "initial-warm")
        for cycle in (1, 2):
            self.generate_one("image", f"cycle-{cycle}-image-1")
            before = len(self.pipeline.native.events)
            self.generate_one("image", f"cycle-{cycle}-image-2")
            if len(self.pipeline.native.events) != before:
                raise RuntimeError("Second image unnecessarily switched residency")
            status, _, _ = request(self.pipeline.native.image_url + "/sdcpp/v1/models/status")
            if status != 200 or len(self.pipeline.native.events) != before:
                raise RuntimeError("Metadata request changed residency")
            if cycle == 1:
                self.generate_one("text", "text-triggered-return")
            self.generate_one("audio", f"cycle-{cycle}-first-speech")
            self.generate_one("audio", f"cycle-{cycle}-warm-speech")
            self.check_pids()
        self.memory.stage = "conversation-concurrent"
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(
                    generate,
                    kind,
                    self.paths,
                    "conversation-concurrent",
                    SPEECH,
                    cfg.KOBOLDCPP_SERVICE.streaming_ui_port,
                )
                for kind in ("text", "audio")
            ]
            for job in jobs:
                job.result()
        self.check_pids()

    def cleanup(self):
        self.stop.set()
        try:
            self.pipeline.close()
        except Exception as error:
            self.report.update(status="failed", cleanup_error=str(error))
        for watcher in self.watchers:
            watcher.join(timeout=3)
        self.report["resources"] = {name: summarize_resources(rows) for name, rows in self.samples.items()}
        (self.paths.logs / "resources.json").write_text(json.dumps(self.samples, indent=2) + "\n")
        (self.paths.artifacts / "vram.json").write_text(json.dumps(self.memory.summary(), indent=2) + "\n")
        deadline = time.monotonic() + 5
        ports = (
            *backends.ports("kobold"),
            cfg.KOBOLDCPP_SERVICE.streaming_ui_port,
            *backends.ports("audio"),
            *backends.ports("image"),
        )
        while any(backends.listening(port) for port in ports) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.report["remaining_ports"] = [port for port in ports if backends.listening(port)]
        if self.report["remaining_ports"]:
            self.report["status"] = "failed"
        self.save()
        print(
            json.dumps({key: self.report.get(key) for key in ("status", "error", "guards", "remaining_ports")}),
            flush=True,
        )

    def controls(self):
        self.memory.stage = "native-proxy-controls"
        checks: tuple[tuple[str, int, str, dict[str, object]], ...] = (
            (
                self.pipeline.native.audio_url,
                cfg.AUDIOCPP_SERVICE.port,
                "/v1/models/unload",
                {"id": "missing-benchmark-model"},
            ),
            (self.pipeline.native.image_url, cfg.SDCPP_SERVICE.port, "/sdcpp/v1/jobs/missing-benchmark-job/cancel", {}),
        )
        for native, port, route, data in checks:
            with (self.paths.logs / "control-stacks.log").open("w") as trace:
                faulthandler.dump_traceback_later(5, file=trace)
                try:
                    self.report["control_check"] = {
                        "route": route,
                        "stage": "proxied-native-first",
                        "request_timeout_seconds": 15,
                    }
                    self.save()
                    proxied = request(f"http://127.0.0.1:{port}" + route, data, timeout=15)
                    self.report["control_check"]["stage"] = "direct-native-second"
                    self.save()
                    direct = request(native + route, data, timeout=15)
                finally:
                    faulthandler.cancel_dump_traceback_later()
            if direct[:2] != proxied[:2] or direct[0] < 400:
                raise RuntimeError("Native error body/status did not pass through unchanged")
        controls = []
        for route, payload in (
            ("/v1/models/unload", {"id": self.pipeline.native.audio_model["id"]}),
            ("/v1/models/load", self.pipeline.native.audio_model),
        ):
            status, response, _ = request(f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}" + route, payload, timeout=90)
            if status != 200:
                raise RuntimeError(f"Native AudioCpp control failed: {response!r}")
            controls.append({"route": route, "status": status})
        with self.pipeline.coordinator.lease("image"):
            for route, payload in (
                ("/sdcpp/v1/models/unload", {}),
                ("/sdcpp/v1/models/load", self.pipeline.native.image_selection),
            ):
                status, response, _ = request(f"http://127.0.0.1:{cfg.SDCPP_SERVICE.port}" + route, payload, timeout=90)
                if status != 200:
                    raise RuntimeError(f"Native sd.cpp control failed: {response!r}")
                controls.append({"route": route, "status": status})
        self.report["passthrough_controls"] = controls
        with self.pipeline.coordinator.lease("conversation"):
            pass
        selection = self.pipeline.native.image_selection
        try:
            self.pipeline.native.image_selection = {"recipe": "nonexistent-recipe", "models": {}}
            status, _, _ = request(
                f"http://127.0.0.1:{cfg.SDCPP_SERVICE.port}/v1/images/generations", {"prompt": "test"}, timeout=90
            )
            if status != 503 or self.pipeline.coordinator.mode != "conversation":
                raise RuntimeError("Failed image load did not restore conversation mode")
        finally:
            self.pipeline.native.image_selection = selection
        self.generate_one("audio", "speech-after-failed-load")
        current = [process.pid for process in self.owned()]
        if current[0] != self.report["native_pids"][0] or current[2] != self.report["native_pids"][2]:
            raise RuntimeError("Fault recovery replaced AudioCpp or Kobold unexpectedly")
        self.report["native_pids_before_fault"] = self.report["native_pids"]
        self.report["native_pids"] = current
        self.report["native_error_passthrough"] = "exact status/body matched"
        self.report["failed_load_recovery"] = "conversation restored; speech succeeded"

    def workload(self):
        with (
            (self.paths.logs / "proxy.log").open("w", encoding="utf-8", buffering=1) as log,
            contextlib.redirect_stdout(log),
            contextlib.redirect_stderr(log),
            self.memory,
        ):
            self.memory.stage = "startup"
            self.pipeline.start()
            self.report["native_pids"] = [process.pid for process in self.owned()]
            self.report["native_selection"] = self.pipeline.native.image_selection
            self.watch_processes()
            if self.controls_only:
                self.controls()
            else:
                self.two_sessions()
            self.check_pids()
            if self.report.get("guard_abort") or any(
                row.get("abort") for rows in self.samples.values() for row in rows
            ):
                raise RuntimeError("Resource guard triggered")
            self.report["status"] = "passed"

    def run(self):
        self.save()
        Thread(target=self.guard, daemon=True).start()
        try:
            self.workload()
        except BaseException as error:
            self.report.update(status="failed", error=str(error))
            raise
        finally:
            self.cleanup()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--controls-only", action="store_true", help="Native passthrough and failed-load recovery; no image generation"
    )
    args = parser.parse_args()
    NativeSessionProbe(args.controls_only).run()


if __name__ == "__main__":
    main()
