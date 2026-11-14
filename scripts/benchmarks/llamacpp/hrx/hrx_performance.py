"""Bounded HRX baseline: one warmup and two deterministic short requests."""

import argparse
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from scripts.benchmarks.llamacpp.benchmark_llamacpp_profiles import await_http, post_json, stop_server
from scripts.benchmarks.shared.paths import BenchmarkPaths, RunPaths
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.llamacpp.llamacpp import LlamaConfig


def compare_runs(previous: Path, current: Path) -> dict[str, Any]:
    old = json.loads((previous / "artifacts/results.json").read_text(encoding="utf-8"))
    new = json.loads((current / "artifacts/results.json").read_text(encoding="utf-8"))

    def options(command: list[str]) -> list[str]:
        result = []
        iterator = iter(command[1:])
        for option in iterator:
            if option == "--log-file":
                next(iterator)
            else:
                result.append(option)
        return result

    if old["model"] != new["model"] or options(old["command"]) != options(new["command"]):
        raise ValueError("Runtime comparisons require the same model and launch options")
    if [r["request"] for r in old["requests"]] != [r["request"] for r in new["requests"]]:
        raise ValueError("Runtime comparisons require identical request settings")
    if len(old["requests"]) != 3 or not old["cleanup_port_clear"] or not new["cleanup_port_clear"]:
        raise ValueError("Comparison requires completed probes with owned servers stopped")
    if any(
        request["response"]["timings"]["predicted_n"] != request["request"]["n_predict"]
        for run in (old, new)
        for request in run["requests"]
    ):
        raise ValueError("Comparison requires complete generated token counts")

    def timings(run: dict[str, Any]) -> dict[str, Any]:
        responses = [r["response"] for r in run["requests"][1:]]
        tokens = sum(r["timings"]["predicted_n"] for r in responses)
        milliseconds = sum(r["timings"]["predicted_ms"] for r in responses)
        return {
            "decode_tps": tokens / (milliseconds / 1000),
            "requests_tps": [r["timings"]["predicted_per_second"] for r in responses],
        }

    before, after = timings(old), timings(new)
    exact = all(
        old["requests"][i]["response"][key] == new["requests"][i]["response"][key]
        for i in range(3)
        for key in ("tokens", "content")
    )
    comparison = {
        "name": "HRX runtime comparison",
        "category": "probes",
        "status": "passed" if exact else "output-changed",
        "previous_run": str(previous),
        "current_run": str(current),
        "model": new["model"],
        "previous": before,
        "current": after,
        "exact_outputs": exact,
        "decode_change_percent": (after["decode_tps"] / before["decode_tps"] - 1) * 100,
        "reasoning": "One matched previous/current pair with one warmup and two measured requests per fresh server; exploratory, not a statistical speedup claim.",
    }
    paths = BenchmarkPaths(__file__).new_run()
    paths.write_report(comparison)
    print(f"[OUTPUT] {paths.root}", flush=True)
    return comparison


def _configure(conf: LlamaConfig, args: argparse.Namespace, paths: RunPaths) -> None:
    conf.profile = replace(
        conf.profile,
        extra_args={
            **conf.profile.extra_args,
            "ctx-size": "8192",
            "cache-type-k": "f16",
            "cache-type-v": "f16",
            "batch-size": "512",
            "ubatch-size": "512",
            "threads": "8",
            "threads-batch": "8",
        },
    )
    if args.runtime is not None:
        conf.build_dir = args.runtime.resolve()
        conf.exe = conf.build_dir / "llama-server.exe"
        conf.build_env["IREE_HAL_AMDGPU_LIBHSA_PATH"] = str(conf.build_dir / "hsa-runtime64.dll")
    if args.device_profile:
        conf.build_env["HRX_PROFILE_FILE"] = str(paths.artifacts / "device.hrxprofile")
        conf.build_env["HRX_PROFILE_MODE"] = "dispatch"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--tokens", type=int, default=16, help="Output tokens per request (default: 16)")
    parser.add_argument("--device-profile", action="store_true", help="Capture HRX dispatch timestamps")
    parser.add_argument(
        "--compare-runs", nargs=2, type=Path, metavar=("PREVIOUS", "CURRENT"), help="Compare two saved probes"
    )
    args = parser.parse_args()
    if args.compare_runs:
        print(json.dumps(compare_runs(*args.compare_runs), indent=2))
        return
    if args.tokens < 16:
        parser.error("--tokens must be at least 16 for the known-good code-prefix check")
    if launch_util.llama_server_running():
        raise RuntimeError("Local llama-server running; confirm session safety")
    port = 9951
    if launch_util.backend_running(port):
        raise RuntimeError(f"Port {port} occupied")
    paths = BenchmarkPaths(__file__).new_run()
    conf = LlamaConfig(
        profile_name="swift15-hrx", build_name="hrx", port=port, ini_overrides={"reasoning": "off", "fit": "off"}
    )
    _configure(conf, args, paths)
    log = paths.logs / "server.log"
    command = conf.build_cmd(paths.logs / "native.log")
    evidence: dict[str, Any] = {
        "command": command,
        "build_env": conf.build_env,
        "model": str(conf.model),
        "hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in conf.build_dir.iterdir()
            if p.suffix in {".dll", ".exe"}
        },
        "inherited_diagnostics": {
            k: v for k, v in os.environ.items() if k.startswith(("GGML_", "HRX_", "HSA_", "ROCR_", "IREE_", "LOOM_"))
        },
        "requests": [],
    }
    started = time.monotonic()
    process = launch_util.launch_process(
        command,
        title="HRX short probe",
        cwd=str(conf.build_dir),
        mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        log_file=str(log),
        env=conf.build_env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        await_http(base, process, 90)
        evidence["startup_seconds"] = time.monotonic() - started
        for index, prompt in enumerate(
            ("Describe a green bicycle.", "int add(int a, int b) { return", "int add(int a, int b) { return")
        ):
            request = {
                "prompt": prompt,
                "n_predict": args.tokens,
                "temperature": 0,
                "seed": 42,
                "ignore_eos": True,
                "cache_prompt": False,
                "return_tokens": True,
            }
            before = time.monotonic()
            response = post_json(f"{base}/completion", request, 90)
            evidence["requests"].append(
                {"request": request, "seconds": time.monotonic() - before, "response": response}
            )
            (paths.artifacts / f"response-{index}.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
            if response["timings"]["predicted_n"] != args.tokens or not response["content"].strip():
                raise RuntimeError("Invalid or incomplete short output")
            if index and not response["content"].startswith(" a + b; }"):
                raise RuntimeError("Code output differs from known-good prefix")
            print(f"[RESULT] request {index}: {response['timings']}", flush=True)
    finally:
        stop_server(process)
        evidence["cleanup_port_clear"] = not launch_util.backend_running(port)
        evidence["total_seconds"] = time.monotonic() - started
        (paths.artifacts / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"[OUTPUT] {paths.root}", flush=True)
        if not evidence["cleanup_port_clear"]:
            raise RuntimeError("Port remained occupied after owned process cleanup")


if __name__ == "__main__":
    main()
