"""Live workflow generation checks and ownership of start/stop workers."""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from collections.abc import Generator
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.reporting import RunReport
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp, audiocpp_proxy
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.llamacpp import llamacpp, llamacpp_coding, llamacpp_dsh
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.launchers.sdcpp import proxy as sdcpp_proxy
from scripts.launchers.sdcpp import server as sdcpp
from scripts.tests.shared import live_stamp
from scripts.tests.shared.http_server import request
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.progress import ProgressBar
from scripts.tests.shared.timing import TimedTextTestResult

live_timeout = 300.0
# - One target per user-facing launch entry. Backend probes cover engines/models
#   that launchers do not exercise; the two sets must stay disjoint.
LAUNCHER_TARGETS: tuple[str, ...] = ("sdcpp", "audiocpp", "llamacpp", "kobold", "dsh-headless", "practice")
# - the installed tree each target launches from, so a moved build marks the row stale
TARGET_COMPONENTS: dict[str, str] = {
    "sdcpp": "sdcpp",
    "audiocpp": "audiocpp",
    "llamacpp": "llamacpp",
    "kobold": "koboldcpp",
    "dsh-headless": "coding_agents/deepseek",
    "practice": "audiocpp",
}


def target_available(name: str) -> tuple[bool, str]:
    if name == "dsh-headless":
        archive = cfg.DEEPSEEK_CLIENT.exe.parent / "resources/app.asar"
        # - The headless entry lives inside app.asar, which is a file, not a directory.
        if not cfg.DEEPSEEK_CLIENT.exe.is_file() or not archive.is_file():
            return False, "DeepSeek Harness headless entry is not installed"
    return True, ""


def audiocpp_payload() -> dict[str, object]:
    return {
        "input": "This is a short framework test.",
        "voice": cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value,
        "model": cfg.AUDIOCPP_SERVICE.model,
        "response_format": "wav",
        # - The proxy defaults to streaming when stream is absent; RIFF requires false.
        "stream": False,
    }


class LiveFrameworks(unittest.TestCase):
    def test_dsh(self):
        self.assertIn(llamacpp.LlamaConfig().alias, llamacpp_dsh.discover_models(cfg.LLAMACPP_SERVICE.port))
        sessions = cfg.DEEPSEEK_CLIENT.home / "sessions"
        before = {path: path.stat().st_mtime_ns for path in sessions.rglob("*") if path.is_file()}
        env = llamacpp_dsh.prepare_dsh_env()
        env["ELECTRON_RUN_AS_NODE"] = "1"
        entry = (
            cfg.DEEPSEEK_CLIENT.exe.parent
            / "resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js"
        )
        cmd = [
            str(cfg.DEEPSEEK_CLIENT.exe),
            "--expose-internals",
            str(entry),
            "--profile",
            "headless",
            "--patch",
            str(cfg.DEEPSEEK_CLIENT.patch_path()),
            "Reply with exactly FRAMEWORK_TEST_OK. Do not call any tools.",
        ]
        with subprocess.Popen(
            cmd,
            cwd=project_cfg.SCRIPTS_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ) as process:
            try:
                launch_util.assign_process_to_job(process.pid)
                output, errors = process.communicate(timeout=live_timeout)
            finally:
                if process.poll() is None:
                    launch_util.kill_process_tree(process.pid)
                    process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, errors[-3000:])
        self.assertNotIn("EPERM", output + errors)
        self.assertIn("FRAMEWORK_TEST_OK", output)
        self.assertTrue(
            any(path.is_file() and path.stat().st_mtime_ns != before.get(path) for path in sessions.rglob("*")),
            "Harness did not persist its session",
        )

    def test_sdcpp(self):
        url = f"http://127.0.0.1:{cfg.SDCPP_SERVICE.port}"
        status, body, _ = request(
            url + "/v1/images/generations",
            {
                "prompt": "a red cube on a white background",
                "width": 256,
                "height": 256,
                "steps": 1,
                "seed": 1,
                "response_format": "b64_json",
                "_skip_save": True,
            },
            timeout=live_timeout,
        )
        self.assertEqual(status, 200, body[:1000])
        image = base64.b64decode(json.loads(body)["data"][0]["b64_json"], validate=True)
        from PIL import Image

        with Image.open(io.BytesIO(image)) as generated:
            self.assertEqual(generated.size, (256, 256))
            generated.verify()

    def test_audiocpp(self):
        url = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}"
        status, body, _ = request(url + "/v1/audio/speech", audiocpp_payload(), timeout=live_timeout)
        self.assertEqual(status, 200, body[:1000])
        self.assertEqual(body[:4], b"RIFF", body[:200])
        with wave.open(io.BytesIO(body), "rb") as wav:
            self.assertGreater(wav.getnframes(), 0)
            pcm = wav.readframes(wav.getnframes())
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertTrue(any(pcm), "generated audio is entirely silent")

    def test_llamacpp(self):
        status, body, _ = request(cfg.llama_base_url() + "/models", timeout=10)
        self.assertEqual(status, 200, body[:1000])
        self.assertIn(llamacpp.LlamaConfig().alias, [entry["id"] for entry in json.loads(body)["data"]])
        for client in (cfg.PI_CLIENT, cfg.LITTLECODER_CLIENT):
            with self.subTest(client=str(client.entry)):
                env = llamacpp_coding.prepare_pi_env(client)
                if client is cfg.PI_CLIENT:
                    cmd = llamacpp_coding.pi_command(llamacpp.LlamaConfig())
                else:
                    cmd = [client.node_cmd, str(client.entry), "--no-update-check", "--model", client.model]
                self.check_coding_client(client, cmd, env)

    def check_coding_client(
        self, client: cfg.SharedStartupRequestCodingClientSettings, cmd: list[str], env: dict[str, str]
    ):
        sessions = client.agent_dir / "sessions"
        previous_sessions = set(sessions.rglob("*.jsonl"))
        cmd = [
            *cmd,
            "--mode",
            "json",
            "-p",
            "--no-tools",
            "Reply with exactly FRAMEWORK_TEST_OK. Do not call any tools.",
        ]
        result = subprocess.run(
            cmd,
            cwd=project_cfg.SCRIPTS_DIR,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=live_timeout,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertNotIn("EPERM", result.stderr + result.stdout)
        self.assertTrue(set(sessions.rglob("*.jsonl")) - previous_sessions, "Pi did not persist its session")
        messages = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "message_end" and event.get("message", {}).get("role") == "assistant":
                messages.append(event["message"])
        self.assertTrue(messages, "Pi did not emit a completed assistant message")
        text = "".join(block.get("text", "") for block in messages[-1]["content"] if block.get("type") == "text")
        self.assertIn("FRAMEWORK_TEST_OK", text)
        self.assertNotEqual(messages[-1].get("stopReason"), "error")

    def test_kobold(self):
        url = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}"
        status, body, _ = request(
            url + "/api/v1/generate",
            {"prompt": "A short greeting: Hello", "max_length": 16, "temperature": 0.1},
            timeout=live_timeout,
        )
        self.assertEqual(status, 200, body[:1000])
        self.assertTrue(json.loads(body)["results"][0]["text"].strip(), "Kobold returned no generated text")

    def test_combined_proxies(self):
        # - Readiness only; standalone AudioCpp/sd.cpp targets own generation.
        targets = []
        for service, path in ((cfg.AUDIOCPP_SERVICE, "/health"), (cfg.SDCPP_SERVICE, "/v1/models")):
            if service.enabled and service.mode == cfg.ServiceMode.PROXY:
                targets.append((service.port, path))
        self.assertTrue(targets, "Kobold combined launch started no proxies")
        for port, path in targets:
            status, body, _ = request(f"http://127.0.0.1:{port}{path}", timeout=10)
            self.assertEqual(status, 200, body[:500])


def kobold_port() -> int:
    value = cfg.KOBOLDCPP_KCPPS_ARGS["port"]
    if not isinstance(value, int):
        raise TypeError("Kobold port must be an integer")
    return value


def workflow_ports(framework: str) -> list[int]:
    if framework in ("llamacpp", "dsh", "dsh-headless"):
        return [cfg.LLAMACPP_SERVICE.port] + (
            [cfg.LLAMACPP_SERVICE.internal_port] if cfg.LLAMACPP_SERVICE.mode == cfg.ServiceMode.PROXY else []
        )
    if framework == "kobold":
        ports = [kobold_port()]
        for service in (cfg.AUDIOCPP_SERVICE, cfg.SDCPP_SERVICE):
            if service.enabled and service.mode == cfg.ServiceMode.PROXY:
                ports.extend((service.port, service.internal_port))
        return ports
    service = cfg.SDCPP_SERVICE if framework == "sdcpp" else cfg.AUDIOCPP_SERVICE
    return [service.port, service.internal_port]


def launch_worker(framework: str, ini_set: list[str] | None = None) -> None:
    # - use existing launchers for ports, commands, config, warmup and proxy wiring
    cfg.LAUNCH.console_terminal_mode = cfg.ConsoleTerminalLaunchMode.MERGE
    sys.argv = ["framework-test-worker", *(["--client", "none"] if framework == "llamacpp" else [])]
    for setting in ini_set or []:
        sys.argv.extend(["--ini-set", setting])
    if framework == "dsh-headless":
        sys.argv.append("--no-open")
    if framework == "sdcpp":
        sdcpp_proxy.main()
    elif framework == "audiocpp":
        audiocpp_proxy.main()
    elif framework == "llamacpp":
        llamacpp_coding.main()
    elif framework in ("dsh", "dsh-headless"):
        llamacpp_dsh.main()
    else:
        kobold.main()


def worker_main(framework: str, ini_set: list[str] | None = None) -> int:
    # - the worker owns the existing kill-on-close job before creating any descendants
    launch_util.assign_process_to_job(os.getpid())
    processes: list[subprocess.Popen[Any]] = []
    stopping = threading.Event()

    def stop_backends(code: int) -> None:
        stopping.set()
        for process in processes:
            if process.poll() is None:
                launch_util.kill_process_tree(process.pid)
        os._exit(code)

    def watch_process(process: subprocess.Popen[Any]) -> None:
        processes.append(process)

        def backend_exited() -> None:
            code = process.wait()
            if stopping.is_set():
                return
            print(f"[FAIL] backend pid {process.pid} exited with {code}", file=sys.stderr, flush=True)
            stop_backends(1)

        threading.Thread(target=backend_exited, daemon=True).start()

    def observed_launch(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        process = launch_util.launch_process(*args, **kwargs)
        watch_process(process)
        return process

    sdcpp.launch_process = observed_launch
    audiocpp.launch_process = observed_launch
    llamacpp.launch_process = observed_launch
    kobold.launch_process = observed_launch

    launch_worker(framework, ini_set)
    # - --client none returns with llama-server running; retain the worker's job handle
    if framework in ("llamacpp", "dsh", "dsh-headless"):
        threading.Event().wait()
    return 1


def _require_free_ports(framework: str, ports: list[int]) -> set[str]:
    old_pids = {pid for _, pid in launch_util._listening_pids({str(port) for port in ports})}
    if old_pids:
        raise RuntimeError(f"Existing {framework} ports are occupied; sessions retained: {sorted(old_pids)}")
    if framework in ("llamacpp", "dsh", "dsh-headless") and launch_util.llama_server_running():
        raise RuntimeError("Existing llama.cpp session retained; isolated workflow check requires free runtimes")
    return old_pids


def _worker_env(output: RunPaths) -> dict[str, str]:
    env = dict(os.environ)
    # - the agent host's PYTHONHOME must not redirect packaged Python backends
    env.pop("PYTHONHOME", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["AI_LOGS_DIR"] = str(output.logs)
    env["AI_OUTPUT_DIR"] = str(output.artifacts)
    return env


def _worker_command(framework: str, ini_overrides: dict[str, str] | None) -> list[str]:
    overrides = [
        argument for key, value in (ini_overrides or {}).items() for argument in ("--ini-set", f"{key}={value}")
    ]
    return [sys.executable, "-m", "scripts.tests.cases.suites.frameworks_smoke", "--worker", framework, *overrides]


def _ready_url(framework: str, ports: list[int]) -> str:
    if framework == "kobold":
        return f"http://127.0.0.1:{kobold_port()}/api/v1/model"
    if framework == "sdcpp":
        return f"http://127.0.0.1:{ports[0]}/v1/models"
    return f"http://127.0.0.1:{ports[0]}/health"


def _ports_ready(ports: list[int], old_pids: set[str], ready_url: str) -> bool:
    try:
        listeners = launch_util._listening_pids({str(port) for port in ports})
        new_ports = {int(port) for port, pid in listeners if pid not in old_pids}
        return set(ports).issubset(new_ports) and request(ready_url, timeout=2)[0] == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def _await_ready(
    worker: subprocess.Popen[Any], framework: str, ports: list[int], old_pids: set[str], ready_url: str, log_path: Path
) -> None:
    deadline = time.monotonic() + live_timeout
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError(f"{framework} launcher exited with {worker.returncode}; see {log_path}")
        if _ports_ready(ports, old_pids, ready_url):
            return
        time.sleep(0.5)
    raise TimeoutError(f"{framework} did not become ready in {live_timeout}s; see {log_path}")


def _stop_worker(worker: subprocess.Popen[Any], framework: str, ports: list[int], log_path: Path) -> None:
    # - taskkill /T also covers packaged executables that escape job inheritance
    if worker.poll() is None:
        launch_util.kill_process_tree(worker.pid)
    if worker.stdin is not None:
        worker.stdin.close()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        launch_util.kill_process_tree(worker.pid)
        worker.wait(timeout=10)
    targets = {str(port) for port in ports}
    deadline = time.monotonic() + 10
    while launch_util._listening_pids(targets) and time.monotonic() < deadline:
        time.sleep(0.25)
    if launch_util._listening_pids(targets):
        raise RuntimeError(f"{framework} shutdown left occupied ports {ports}; see {log_path}")
    print(f"[STOPPED] {framework}: ports released", flush=True)


@contextlib.contextmanager
def running_framework(
    framework: str, output: RunPaths | None = None, ini_overrides: dict[str, str] | None = None
) -> Generator[Path]:
    if sys.platform != "win32":
        raise RuntimeError("live start/stop tests require Windows")
    ports = workflow_ports(framework)
    old_pids = _require_free_ports(framework, ports)
    output = output or CasePaths(__file__).new_run()
    log_path = output.logs / f"{framework}_{time.time_ns()}.log"
    with log_path.open("wb") as log:
        worker = subprocess.Popen(
            _worker_command(framework, ini_overrides),
            cwd=project_cfg.BASE_DIR,
            env=_worker_env(output),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            launch_util.assign_process_to_job(worker.pid)
            print(f"[START] {framework}: reserved free ports {ports}; log: {log_path}", flush=True)
            _await_ready(worker, framework, ports, old_pids, _ready_url(framework, ports), log_path)
            print(f"[READY] {framework}", flush=True)
            yield log_path
        finally:
            _stop_worker(worker, framework, ports, log_path)


def run_live(frameworks: list[str]) -> bool:
    if live_stamp.unchanged("launchers", frameworks):
        print(
            f"[SKIP] launchers: sources unchanged since the last pass ({', '.join(frameworks)}); "
            "set AI_LIVE_FORCE=1 to rerun",
            flush=True,
        )
        return True
    context = dict(require_native_execution("Native framework workflows"))
    from scripts.tests.shared.native_suites import native_policy, refuse_existing_sessions

    with native_policy():
        launch_util.assign_current_process_to_job()
        refuse_existing_sessions()
        passed = _run_live(frameworks, context)
    if passed:
        live_stamp.record("launchers", frameworks)
    return passed


def run_practice(output: RunPaths) -> tuple[bool, Path]:
    """Language/test stack through the saved-PCM gateway (llama.cpp runtime)."""
    log_path = output.logs / f"practice_{time.time_ns()}.log"
    command = [sys.executable, "-m", "scripts.tests.cases.asr.shared.practice_smoke", "--runtimes", "llamacpp"]
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=project_cfg.BASE_DIR,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        launch_util.assign_process_to_job(process.pid)
        try:
            code = process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            launch_util.kill_process_tree(process.pid)
            process.wait(timeout=15)
            return False, log_path
    return code == 0, log_path


def _run_live(frameworks: list[str], context: dict[str, Any]) -> bool:
    output = CasePaths(__file__).new_run()
    report = RunReport("native/launchers", "native-launchers")
    report.settings["execution_context"] = context
    report.record_provenance(
        models=[],
        frameworks=[
            provenance.framework_state(TARGET_COMPONENTS[name]) for name in frameworks if name in TARGET_COMPONENTS
        ],
    )
    report.save(output)
    rows: list[dict[str, Any]] = []
    progress = ProgressBar(len(frameworks), "launchers")
    console_title = os.environ.get("AI_TEST_TITLE", "Live Launchers")
    launch_util.set_console_title(console_title)
    passed = True
    for name in frameworks:
        available, reason = target_available(name)
        started = time.perf_counter()
        progress.update(name)
        row: dict[str, Any] = {"target": name, "kind": "launcher", "status": "running"}
        if not available:
            row.update(status="skipped", reason=reason)
            print(f"[SKIP] {name}: {reason}", flush=True)
        else:
            try:
                if name == "practice":
                    ok, log_path = run_practice(output)
                    row.update(status="completed" if ok else "failed", log=str(log_path))
                else:
                    with running_framework(name, output) as log_path:
                        method = "test_dsh" if name == "dsh-headless" else f"test_{name}"
                        suite = unittest.TestSuite([LiveFrameworks(method)])
                        if name == "kobold":
                            suite.addTest(LiveFrameworks("test_combined_proxies"))
                        result = unittest.TextTestRunner(verbosity=2, resultclass=TimedTextTestResult).run(suite)
                        row["tests"] = getattr(result, "case_seconds", {})
                        row.update(status="completed" if result.wasSuccessful() else "failed", log=str(log_path))
                passed = row["status"] != "failed" and passed
            except Exception as error:
                print(f"[FAIL] {name}: {error}", file=sys.stderr)
                row.update(status="failed", reason=str(error))
                passed = False
        row["seconds"] = round(time.perf_counter() - started, 3)
        rows.append(row)
        report.results = rows
        report.status = "completed" if passed else "failed"
        report.save(output)
        print(f"[TIME] {name}: {row['seconds']:.3f}s", flush=True)
        launch_util.set_console_title(console_title)
    report.status = "completed" if passed else "failed"
    report.results = rows
    report.save(output)
    launch_util.set_console_title(console_title)
    print(f"[RESULTS] {output.artifacts}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=(*LAUNCHER_TARGETS, "all"), default=list(LAUNCHER_TARGETS))
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    global live_timeout
    live_timeout = args.timeout
    targets: list[str] = (
        list(LAUNCHER_TARGETS) if "all" in args.only else [str(name) for name in args.only if name != "all"]
    )
    return 0 if run_live(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
