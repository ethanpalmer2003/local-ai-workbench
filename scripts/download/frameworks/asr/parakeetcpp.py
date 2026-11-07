"""Build a pinned CPU streaming library; official release installations stay separate."""

import json
import shutil
import subprocess
import time

from scripts.config import project_config as project_cfg
from scripts.download.frameworks.native_build import visual_studio_environment, run
from scripts.launchers.runtime.execution_context import require_native_execution


def main():
    context = require_native_execution("Parakeet CPU streaming library build")
    component = project_cfg.component("asr/parakeetcpp")
    source = component.framework_dir / "additions/source-v0.6.1"
    build = component.framework_dir / "additions/build-v0.6.1-cpu-stream"
    destination = component.framework_dir / "cpu-stream"
    logs = component.logs_dir / "builds" / str(time.time_ns())
    logs.mkdir(parents=True, exist_ok=True)
    print(f"[LOGS] {logs}", flush=True)
    env = visual_studio_environment("asr/parakeetcpp")
    cmake, ninja = shutil.which("cmake", path=env.get("PATH")), shutil.which("ninja", path=env.get("PATH"))
    if not cmake or not ninja:
        raise RuntimeError("Installed CMake and Ninja are required")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", "--branch", "v0.6.1", "https://github.com/mudler/parakeet.cpp.git", str(source)], logs / "clone.log", timeout=90)
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=10).strip()
    if not commit.startswith("5c9b0fb"):
        raise RuntimeError(f"Unexpected v0.6.1 commit: {commit}")
    if subprocess.check_output(["git", "-C", str(source), "diff", "--name-only"], text=True, timeout=10).strip():
        raise RuntimeError("Source has local changes; review them before rebuilding")
    run(["git", "-C", str(source), "submodule", "update", "--init", "--depth", "1", "third_party/ggml"], logs / "submodule.log", timeout=90)
    destination.mkdir(parents=True, exist_ok=True)
    options = ["-DPARAKEET_SHARED=ON", "-DPARAKEET_BUILD_CLI=OFF", "-DPARAKEET_BUILD_SERVER=OFF",
               "-DPARAKEET_WITH_CED=OFF", "-DPARAKEET_WITH_VOICEDETECT=OFF", "-DPARAKEET_GGML_VULKAN=OFF",
               "-DPARAKEET_GGML_CUDA=OFF", "-DPARAKEET_GGML_HIP=OFF", "-DGGML_NATIVE=ON",
               "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_MAKE_PROGRAM={ninja}",
               f"-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={destination}", f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={destination}",
               "-DBASH_EXECUTABLE=FALSE"]
    run([cmake, "-S", str(source), "-B", str(build), "-G", "Ninja", *options], logs / "configure.log", env, 60)
    run([cmake, "--build", str(build), "--target", "parakeet", "--parallel", "6"], logs / "build.log", env, 240)
    if not (destination / "parakeet.dll").is_file():
        raise RuntimeError(f"Build did not produce parakeet.dll; see {logs}")
    (destination / ".build_manifest.json").write_text(json.dumps({"source_commit": commit, "tag": "v0.6.1",
        "execution_context": context, "options": options, "logs": str(logs)}, indent=2), encoding="utf-8")
    print(f"[OK] {destination / 'parakeet.dll'}", flush=True)


if __name__ == "__main__":
    main()
