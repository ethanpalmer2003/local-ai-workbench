"""Existing proxies share one residency coordinator; native servers stay running."""

import json
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Condition, Event, Lock, Thread
from typing import Any
from urllib.parse import urlsplit

from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.config.shared import image_on_demand as demand_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp, audiocpp_proxy
from scripts.launchers.audiocpp.tts_proxy import run_tts_json_proxy
from scripts.launchers.koboldcpp import kobold_lite
from scripts.launchers.proxy_util import run_json_proxy
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.sdcpp import proxy as sdcpp_proxy
from scripts.launchers.sdcpp import server as sdcpp
from scripts.shared.wait import http_ready, wait_ready

IMAGE_REQUESTS = frozenset(
    {
        "/v1/images/generations",
        "/v1/images/edits",
        "/sdapi/v1/txt2img",
        "/sdapi/v1/img2img",
        "/sdcpp/v1/img_gen",
        "/sdcpp/v1/vid_gen",
        "/sdcpp/v1/upscale",
    }
)
TEXT_REQUESTS = frozenset({"/api/v1/generate", "/api/extra/generate/stream", "/v1/chat/completions", "/v1/completions"})


class ResidencyCoordinator:
    """FIFO mode changes; same-mode generations may run concurrently."""

    def __init__(self, change: Callable[[str], None], timeout: float):
        self.change, self.timeout = change, timeout
        self.condition = Condition()
        self.queue: deque[object] = deque()
        self.mode: str | None = None
        self.active = 0
        self.switching = False
        self.closed = False

    @contextmanager
    def lease(self, target: str):
        ticket = object()
        deadline = time.monotonic() + self.timeout
        with self.condition:
            self.queue.append(ticket)
            self.condition.notify_all()
        acquired = False
        try:
            self._acquire(target, ticket, deadline)
            acquired = True
            yield
        finally:
            with self.condition:
                if acquired:
                    self.active -= 1
                elif ticket in self.queue:
                    self.queue.remove(ticket)
                self.condition.notify_all()

    def _turn(self, target: str, ticket: object) -> str:
        if self.closed:
            raise RuntimeError("Image-session launcher is stopping")
        if self.queue[0] is ticket and not self.switching:
            if self.mode == target:
                self.queue.popleft()
                self.active += 1
                self.condition.notify_all()
                return "acquired"
            if self.active == 0:
                self.switching = True
                return "switch"
        return "wait"

    def _acquire(self, target: str, ticket: object, deadline: float) -> None:
        while True:
            with self.condition:
                turn = self._turn(target, ticket)
                if turn == "acquired":
                    return
                if turn == "wait":
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Waiting for the active generation/model transition timed out")
                    self.condition.wait(remaining)
                    continue
            self._change(target)

    def _change(self, target: str) -> None:
        try:
            self.change(target)
        except BaseException:
            with self.condition:
                self.mode, self.switching = None, False
                self.condition.notify_all()
            raise
        with self.condition:
            self.mode, self.switching = target, False
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()


def ensure_native_catalog() -> Path:
    """Expose the existing sd.cpp folder through its required checkpoint category."""
    root = project_cfg.HF_MODELS_DIR.resolve()
    model = Path(cfg.SDCPP_MODELS[cfg.SDCPP_SERVICE.model]).resolve()
    if not model.is_relative_to(root):
        raise ValueError("Native image catalog requires the configured model beneath HF_MODELS_DIR")
    alias = root / "checkpoints"
    if not alias.exists():
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(model.parent)],
            check=True,
            capture_output=True,
            text=True,
        )
    candidate = alias / model.name
    if not candidate.is_file() or not candidate.samefile(model):
        raise ValueError(f"Existing {alias} does not expose the configured checkpoint; no files were replaced")
    return root


class NativeModelSessions:
    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or project_cfg.component("shared").logs_dir / "image_on_demand" / time.strftime(
            "%Y%m%d-%H%M%S"
        )
        self.processes: list[subprocess.Popen[Any]] = []
        self.events: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.restarts: list[dict[str, Any]] = []
        self.model_root: Path | None = None
        self.audio_url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"
        self.image_url = f"http://127.0.0.1:{cfg.SDCPP_SERVICE.internal_port}"
        source = audio_cfg.read(Path(cfg.AUDIOCPP_SERVER_ARGS["config"]))
        self.audio_model = next(model for model in source["models"] if model["id"] == cfg.AUDIOCPP_SERVICE.model)
        self.image_selection: dict[str, Any] = {}
        self.image_lock = Lock()

    def call(self, base: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        try:
            return self._call_native(base, path, payload)
        finally:
            self.calls.append(
                {"path": path, "seconds": time.monotonic() - started, "method": "GET" if payload is None else "POST"}
            )

    def _call_native(self, base: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        deadline = time.monotonic() + demand_cfg.SETTINGS.transition_timeout_seconds
        while True:
            request = urllib.request.Request(
                base + path,
                None if payload is None else json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            try:
                timeout = min(demand_cfg.SETTINGS.native_request_timeout_seconds, max(1, deadline - time.monotonic()))
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code != 409 or time.monotonic() >= deadline:
                    error.close()
                    raise
                error.close()
                time.sleep(demand_cfg.SETTINGS.busy_retry_seconds)

    def start(self) -> None:
        root = ensure_native_catalog()
        self.model_root = root
        self._start_servers(root)
        self._wait_for_servers()
        self._select_image()

    def _start_servers(self, root: Path) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for name, port in (
            ("audiocpp", cfg.AUDIOCPP_SERVICE.internal_port),
            ("sdcpp", cfg.SDCPP_SERVICE.internal_port),
        ):
            if launch_util.port_listening(port):
                raise RuntimeError(f"An existing {name} instance cannot be owned by image-session mode")
        self.processes.append(
            audiocpp.launch(
                port=cfg.AUDIOCPP_SERVICE.internal_port,
                extra_args=["--ui-management"],
                report_vram=False,
                mode=cfg.ConsoleTerminalLaunchMode.MERGE,
                log_file=str(self.log_dir / "audiocpp-native.log"),
            )
        )
        self.processes.append(self._start_image_server())

    def _start_image_server(self):
        if self.model_root is None:
            raise RuntimeError("Native model catalog has not been prepared")
        return sdcpp.launch(
            port=cfg.SDCPP_SERVICE.internal_port,
            extra_args=["--usage-profile", "shared", "--model-dir", str(self.model_root)],
            mode=cfg.ConsoleTerminalLaunchMode.MERGE,
            load_model_on_start=False,
            log_file=str(self.log_dir / f"sdcpp-native-{len(self.restarts)}.log"),
        )

    def _restart_image_server(self, reason: Exception) -> None:
        started = time.monotonic()
        process = self.processes[1]
        old_pid = process.pid
        print(f"[image-session] Native sd.cpp control failed; restarting owned server: {reason}", flush=True)
        if process.poll() is None:
            launch_util.kill_process_tree(process.pid)
            process.wait(timeout=20)
        deadline = time.monotonic() + 10
        while launch_util.port_listening(cfg.SDCPP_SERVICE.internal_port):
            if time.monotonic() >= deadline:
                raise RuntimeError("sd.cpp port is still occupied; refusing to replace an unowned listener")
            time.sleep(0.1)
        self.restarts.append({"reason": str(reason), "old_pid": old_pid})
        self.processes[1] = self._start_image_server()
        self._wait_for_servers()
        self.restarts[-1].update(new_pid=self.processes[1].pid, seconds=time.monotonic() - started)

    def _unload_image(self) -> None:
        try:
            self.call(self.image_url, "/sdcpp/v1/models/unload", {})
        except urllib.error.HTTPError:
            raise
        except Exception as error:
            self._restart_image_server(error)

    def _wait_for_servers(self) -> None:
        for name, port, process in zip(
            ("audiocpp", "sdcpp"),
            (cfg.AUDIOCPP_SERVICE.internal_port, cfg.SDCPP_SERVICE.internal_port),
            self.processes,
            strict=True,
        ):
            wait_ready(
                lambda name=name, port=port: http_ready(ready_url(name, port), strict=True),
                90,
                label=f"{name} native management",
                process=process,
                interval=0.25,
            )

    def _select_image(self) -> None:
        recipes = self.call(self.image_url, "/sdcpp/v1/recipes")["recipes"]
        recipe = demand_cfg.SETTINGS.image_recipe
        if not any(row["id"] == recipe for row in recipes):
            raise ValueError(
                f"Native recipe {recipe!r} missing; available SD recipes: {[r['id'] for r in recipes if 'sd' in r['id']]}"
            )
        filename = Path(cfg.SDCPP_MODELS[cfg.SDCPP_SERVICE.model]).name
        files = self.call(self.image_url, "/sdcpp/v1/model-files")["files"]
        selected = [row for row in files if Path(row["relative_path"]).name == filename]
        if len(selected) != 1:
            raise ValueError(f"Native checkpoint selection is missing/ambiguous for {filename}")
        self.image_selection = {"recipe": recipe, "models": {"model": selected[0]["id"]}}

    def change(self, target: str) -> None:
        started = time.monotonic()
        print(f"[image-session] Switching to {target}", flush=True)
        if target == "image":
            self.call(self.audio_url, "/v1/models/unload", {"id": self.audio_model["id"]})
            try:
                self.call(self.image_url, "/sdcpp/v1/models/load", self.image_selection)
            except BaseException:
                try:
                    self._unload_image()
                    self.call(self.audio_url, "/v1/models/load", self.audio_model)
                except Exception:
                    traceback.print_exc()
                raise
        else:
            self._unload_image()
            self.call(self.audio_url, "/v1/models/load", self.audio_model)
        self.events.append({"mode": target, "seconds": time.monotonic() - started})
        print(f"[image-session] {target} ready in {self.events[-1]['seconds']:.2f}s", flush=True)

    def ensure_image_loaded(self) -> None:
        with self.image_lock:
            if self.call(self.image_url, "/sdcpp/v1/models/status")["state"] != "ready":
                self.call(self.image_url, "/sdcpp/v1/models/load", self.image_selection)

    def close(self) -> None:
        errors = []
        for process in reversed(self.processes):
            try:
                if process.poll() is None:
                    launch_util.kill_process_tree(process.pid)
                    process.wait(timeout=20)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Native server cleanup failed", errors)


class ImageSessionPipeline:
    def __init__(self, start_kobold: Callable[[], subprocess.Popen[Any]], log_dir: Path | None = None):
        self.start_kobold = start_kobold
        self.native = NativeModelSessions(log_dir)
        self.coordinator = ResidencyCoordinator(self.native.change, demand_cfg.SETTINGS.transition_timeout_seconds)
        self.servers: list[ThreadingHTTPServer] = []
        self.threads: list[Thread] = []
        self.stopping = Event()
        self.kobold_process: subprocess.Popen[Any] | None = None

    def scope(self, backend: str):
        @contextmanager
        def scope(method: str, path: str):
            route = urlsplit(path).path
            image = backend == "image" and route in IMAGE_REQUESTS
            speech = backend == "audio" and route.startswith("/v1/audio/")
            text = backend == "kobold" and route in TEXT_REQUESTS
            target = "image" if image else "conversation"
            context = (
                self.coordinator.lease(target) if method == "POST" and (image or speech or text) else nullcontext()
            )
            try:
                with context:
                    if method == "POST" and image:
                        self.native.ensure_image_loaded()
                    yield
            except Exception:
                if method == "POST" and image:
                    try:
                        with self.coordinator.lease("conversation"):
                            pass
                    except Exception:
                        traceback.print_exc()
                raise

        return scope

    def start_frontend(self, action) -> None:
        def run():
            try:
                action()
            except Exception:
                traceback.print_exc()
            finally:
                self.stopping.set()

        thread = Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def start(self) -> None:
        self._check_ports()
        self.kobold_process = self.start_kobold()
        self.native.start()
        self._start_proxies()
        deadline = time.monotonic() + 30
        while len(self.servers) != 3:
            if self.stopping.is_set() or time.monotonic() >= deadline:
                raise RuntimeError("Image-session proxies did not start")
            time.sleep(0.1)
        with self.coordinator.lease("conversation"):
            pass
        audiocpp_proxy._trigger_audiocpp_preload()

    def _check_ports(self) -> None:
        if launch_util.llama_server_running():
            raise RuntimeError("Existing llama-server is active; it was not stopped")
        kobold_port = cfg.KOBOLDCPP_KCPPS_ARGS["port"]
        if not isinstance(kobold_port, int):
            raise TypeError("Kobold port must be an integer")
        ports = (
            kobold_port,
            cfg.KOBOLDCPP_SERVICE.streaming_ui_port,
            cfg.AUDIOCPP_SERVICE.port,
            cfg.AUDIOCPP_SERVICE.internal_port,
            cfg.SDCPP_SERVICE.port,
            cfg.SDCPP_SERVICE.internal_port,
        )
        if any(launch_util.port_listening(port) for port in ports):
            raise RuntimeError("A required port is occupied; image-session mode will not replace existing services")

    def _start_proxies(self) -> None:
        self.start_frontend(
            lambda: run_tts_json_proxy(
                cfg.AUDIOCPP_SERVICE,
                self.native.audio_url,
                transform=audiocpp_proxy._transform,
                tag="audiocpp-proxy",
                request_scope=self.scope("audio"),
                on_server=self.servers.append,
            )
        )
        self.start_frontend(
            lambda: run_json_proxy(
                cfg.SDCPP_SERVICE,
                self.native.image_url,
                transform=sdcpp_proxy._transform,
                on_response=sdcpp.save_generated_images,
                tag="sdcpp-proxy",
                transform_paths=sdcpp_proxy.TRANSFORM_PATHS,
                request_scope=self.scope("image"),
                on_server=self.servers.append,
            )
        )
        self.start_frontend(
            lambda: kobold_lite.run_proxy(request_scope=self.scope("kobold"), on_server=self.servers.append)
        )

    def close(self) -> None:
        self.coordinator.close()
        self.stopping.set()
        errors = []
        try:
            self.native.close()
        except Exception as error:
            errors.append(error)
        try:
            if self.kobold_process is not None and self.kobold_process.poll() is None:
                launch_util.kill_process_tree(self.kobold_process.pid)
                self.kobold_process.wait(timeout=20)
        except Exception as error:
            errors.append(error)
        for server in self.servers:
            try:
                server.shutdown()
            except Exception as error:
                errors.append(error)
        for thread in self.threads:
            thread.join(timeout=5)
        if errors:
            raise ExceptionGroup("Image-session cleanup failed", errors)


def run(start_kobold: Callable[[], subprocess.Popen[Any]], open_ui: Callable[[], None] | None = None) -> None:
    pipeline = ImageSessionPipeline(start_kobold)
    try:
        pipeline.start()
        if open_ui is not None:
            Thread(target=open_ui, daemon=True).start()
        while not pipeline.stopping.wait(1):
            if any(process.poll() is not None for process in pipeline.native.processes) or (
                pipeline.kobold_process is not None and pipeline.kobold_process.poll() is not None
            ):
                raise RuntimeError("An owned native server exited; stopping image-session mode")
    except KeyboardInterrupt:
        print("[image-session] Stopping")
    finally:
        pipeline.close()
