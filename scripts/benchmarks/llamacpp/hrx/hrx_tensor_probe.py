"""Build and run an isolated native tensor capture, then compare matching boundaries."""

import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from scripts.benchmarks.shared.paths import BenchmarkPaths, Outcome, RunPaths
from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg

HRX_ROOT = project_cfg.FRAMEWORKS_DIR / "llamacpp/additions/hrx"
LLAMA_SOURCE = HRX_ROOT / "llama.cpp"
RUNTIME_BIN = project_cfg.TEST_OUTPUT_DIR / "probes/hrx_backend/verified/20261010-codebook-dispatch/temp/bin"
MODEL = model_cfg.path("llamacpp/Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp")


def native_build_environment() -> tuple[Path, dict[str, str]]:
    msvc = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207")
    sdk = Path("C:/Program Files (x86)/Windows Kits/10")
    sdk_version = "10.0.26100.0"
    env = os.environ.copy()
    env["INCLUDE"] = ";".join(
        str(p) for p in [msvc / "include", *(sdk / "Include" / sdk_version / d for d in ("ucrt", "shared", "um"))]
    )
    env["LIB"] = ";".join(
        str(p) for p in [msvc / "lib/x64", *(sdk / "Lib" / sdk_version / d / "x64" for d in ("ucrt", "um"))]
    )
    return msvc / "bin/Hostx64/x64/cl.exe", env


def build(output: Path) -> Path:
    compiler, env = native_build_environment()
    output.mkdir(parents=True, exist_ok=True)
    for dll in RUNTIME_BIN.glob("*.dll"):
        shutil.copy2(dll, output / dll.name)
    for dll in (
        HRX_ROOT / "build/hrx/libhrx/src/libhrx/Release/hrx.dll",
        HRX_ROOT / "build/rocr/rocr/runtime/Release/hsa-runtime64.dll",
    ):
        shutil.copy2(dll, output / dll.name)
    exe = output / "hrx-tensor-probe.exe"
    command = [
        str(compiler),
        "/nologo",
        "/std:c++17",
        "/EHsc",
        "/MD",
        "/O2",
        "/W4",
        "/D_CRT_SECURE_NO_WARNINGS",
        f"/I{LLAMA_SOURCE / 'include'}",
        f"/I{LLAMA_SOURCE / 'ggml/include'}",
        str(Path(__file__).with_suffix(".cpp")),
        f"/Fe:{exe}",
        f"/Fo:{output / 'probe.obj'}",
        "/link",
        str(HRX_ROOT / "build/llamacpp/src/Release/llama.lib"),
        str(HRX_ROOT / "build/llamacpp/ggml/src/Release/ggml.lib"),
        str(HRX_ROOT / "build/llamacpp/ggml/src/Release/ggml-base.lib"),
    ]
    subprocess.run(command, env=env, check=True, cwd=output)
    return exe


def run(
    exe: Path, output: Path, device: str, tensor_filter: str, prompt: str, chunk_size: int | None
) -> dict[str, Any]:
    env = os.environ.copy()
    env["ROCR_VISIBLE_DEVICES"] = "1"
    env["ROCR_USE_PM4"] = "1"
    env["IREE_HAL_AMDGPU_LIBHSA_PATH"] = str(HRX_ROOT / "build/rocr/rocr/runtime/Release/hsa-runtime64.dll")
    env.pop("HSA_OVERRIDE_GFX_VERSION", None)
    env.pop("HRX_PROBE_CHUNK_SIZE", None)
    if chunk_size is not None:
        env["HRX_PROBE_CHUNK_SIZE"] = str(chunk_size)
    env["PATH"] = str(exe.parent) + os.pathsep + env["PATH"]
    output.mkdir(parents=True, exist_ok=True)
    logs = output.parent.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with (
        (logs / f"{device}.stdout.log").open("w", encoding="utf-8") as stdout,
        (logs / f"{device}.stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        result = subprocess.run(
            [str(exe), str(MODEL), device, str(output), tensor_filter, prompt, "264"],
            env=env,
            cwd=exe.parent,
            stdout=stdout,
            stderr=stderr,
            timeout=240,
        )
    return {
        "device": device,
        "filter": tensor_filter,
        "chunk_size": chunk_size,
        "exit_code": result.returncode,
        "seconds": time.monotonic() - start,
    }


def compare(reference: Path, actual: Path) -> list[dict[str, Any]]:
    import numpy as np

    if (reference / "tokens.txt").read_bytes() != (actual / "tokens.txt").read_bytes():
        raise ValueError("input tokens differ")

    def tensors(directory: Path) -> dict[tuple[str, str], list[str]]:
        with (directory / "tensors.tsv").open(encoding="utf-8", newline="") as stream:
            return {(row[0], row[1]): row for row in csv.reader(stream, delimiter="\t")}

    refs, acts = tensors(reference), tensors(actual)
    results = []
    for key, row in refs.items():
        if key not in acts:
            results.append({"step": key[0], "tensor": key[1], "status": "missing"})
            continue
        other = acts[key]
        if row[4] != other[4]:
            raise ValueError(f"shape mismatch for {key}: {row[4]} != {other[4]}")
        expected = np.fromfile(reference / row[5], dtype="<f4").astype(np.float64)
        observed = np.fromfile(actual / other[5], dtype="<f4").astype(np.float64)
        diff = observed - expected
        rms = float(np.sqrt(np.mean(expected**2)))
        results.append(
            {
                "step": key[0],
                "tensor": key[1],
                "op": other[2],
                "buffer": other[3],
                "max_abs": float(np.max(np.abs(diff))),
                "relative_rmse": float(np.sqrt(np.mean(diff**2)) / max(rms, 1e-12)),
                "finite": bool(np.isfinite(observed).all()),
            }
        )
    for step in range(2):
        expected = np.fromfile(reference / f"{step}-logits.f32", dtype="<f4").astype(np.float64)
        observed = np.fromfile(actual / f"{step}-logits.f32", dtype="<f4").astype(np.float64)
        results.append(
            {
                "step": str(step),
                "tensor": "logits",
                "max_abs": float(np.max(np.abs(expected - observed))),
                "reference_top": int(expected.argmax()),
                "actual_top": int(observed.argmax()),
            }
        )
    return results


def _server_env(exe: Path, runtime: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env["ROCR_VISIBLE_DEVICES"] = "1"
    env["ROCR_USE_PM4"] = "1"
    env["IREE_HAL_AMDGPU_LIBHSA_PATH"] = str(
        runtime / "hsa-runtime64.dll" if runtime else HRX_ROOT / "build/rocr/rocr/runtime/Release/hsa-runtime64.dll"
    )
    env.pop("HSA_OVERRIDE_GFX_VERSION", None)
    env["PATH"] = str(exe.parent) + os.pathsep + env["PATH"]
    return env


def _server_command(server: Path, port: int, device: str) -> list[str]:
    command = [
        str(server),
        "-m",
        str(MODEL),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "-c",
        "512",
        "-np",
        "1",
        "-ngl",
        "0" if device == "cpu" else "99",
        "-fa",
        "on",
        "-ctk",
        "f16",
        "-ctv",
        "f16",
        "--reasoning",
        "off",
        "--spec-type",
        "none",
        "--no-warmup",
    ]
    command.extend(["-t", "8", "-tb", "8", "--device", "none" if device == "cpu" else "HRX0"])
    if device == "cpu":
        command.append("--no-kv-offload")
    return command


def server_smoke(exe: Path, paths: RunPaths, device: str, predict: int, runtime: Path | None = None) -> dict[str, Any]:
    import urllib.request

    from scripts.launchers import launch_util

    if launch_util.llama_server_running():
        raise RuntimeError("local configured llama-server is running; confirm session safety before server launch")
    port = 9950
    if launch_util.backend_running(port):
        raise RuntimeError(f"probe port {port} is already occupied")
    server = (runtime or exe.parent) / "llama-server.exe"
    if runtime is None and server.resolve() != (RUNTIME_BIN / server.name).resolve():
        shutil.copy2(RUNTIME_BIN / server.name, server)
    env = _server_env(exe, runtime)
    command = _server_command(server, port, device)
    start = time.monotonic()
    results = []
    with (
        (paths.logs / "server.stdout.log").open("w", encoding="utf-8") as stdout,
        (paths.logs / "server.stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            command, env=env, cwd=exe.parent, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW
        )
        try:
            deadline = time.monotonic() + 60
            while not launch_util.backend_running(port, timeout=1):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("probe server failed to become ready; see server.stderr.log")
                time.sleep(0.2)
            requests = [
                (
                    "code",
                    "/completion",
                    {
                        "prompt": "int add(int a, int b) { return",
                        "n_predict": predict,
                        "temperature": 0,
                        "ignore_eos": True,
                        "return_tokens": True,
                    },
                ),
                (
                    "chat",
                    "/v1/chat/completions",
                    {
                        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                        "max_tokens": 16,
                        "temperature": 0,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                ),
            ]
            for name, endpoint, body in requests:
                (paths.artifacts / f"{name}-request.json").write_text(
                    json.dumps(body, indent=2) + "\n", encoding="utf-8"
                )
                request_start = time.monotonic()
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}{endpoint}",
                    json.dumps(body).encode(),
                    {"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=90) as response:
                    payload = json.load(response)
                (paths.artifacts / f"{name}-response.json").write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
                content = payload["content"] if name == "code" else payload["choices"][0]["message"].get("content")
                results.append({"mode": name, "content": content, "seconds": time.monotonic() - request_start})
                print(json.dumps(results[-1]), flush=True)
        finally:
            process.terminate()
            process.wait(timeout=10)
    return {
        "device": device,
        "predict": predict,
        "results": results,
        "seconds": time.monotonic() - start,
        "owned_server_stopped": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--backend-dll", type=Path)
    parser.add_argument("--server-smoke", action="store_true")
    parser.add_argument("--server-device", choices=("cpu", "HRX0"), default="HRX0")
    parser.add_argument("--predict", type=int, default=8)
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--device", choices=("cpu", "HRX0"))
    parser.add_argument("--filter", default="l_out-[0-9]+|result_output")
    parser.add_argument("--prompt", default="int add(int a, int b) { return")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--actual", type=Path)
    args = parser.parse_args()
    if args.chunk_size is not None and args.filter != "-":
        parser.error("chunk comparison requires --filter - to preserve fusion")
    if args.backend_dll and args.exe:
        parser.error("--backend-dll requires a new isolated build; omit --exe")
    if args.reference and args.actual:
        comparison = compare(args.reference, args.actual)
        comparison_file = args.actual / f"comparison-{args.reference.parent.parent.name}.json"
        comparison_file.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(comparison, indent=2))
        return
    paths = BenchmarkPaths(__file__).new_run(Outcome.INCONCLUSIVE)
    start = time.monotonic()
    exe = args.exe or build(paths.temp / "bin")
    if args.backend_dll:
        shutil.copy2(args.backend_dll, exe.parent / "ggml-hrx.dll")
    result: dict[str, Any] = {"name": "hrx_tensor_probe", "category": "probes", "status": "built", "exe": str(exe)}
    if args.server_smoke:
        result.update(server_smoke(exe, paths, args.server_device, args.predict))
        result["status"] = "smoke-completed"
    elif args.device:
        result.update(run(exe, paths.artifacts / args.device, args.device, args.filter, args.prompt, args.chunk_size))
        result["status"] = "captured" if result["exit_code"] == 0 else "failed"
    result["total_seconds"] = time.monotonic() - start
    paths.write_report(result)
    print(json.dumps({"run": str(paths.root), **result}, indent=2))
    if result.get("exit_code", 0) != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
