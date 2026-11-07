"""Build the current upstream Whisper release for Windows Vulkan."""

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import github
from scripts.download.frameworks import native_build
from scripts.download.frameworks.native_build import run as run
from scripts.download.frameworks.update_shared import UpdateError, replace_installation
from scripts.download.frameworks.update_types import ToolSpec
from scripts.launchers.runtime.execution_context import require_native_execution


def visual_studio_environment() -> dict[str, str]:
    return native_build.visual_studio_environment("asr/whispercpp")


def latest_source_tag(tool: ToolSpec) -> str:
    release = github.get_json(f"{github.API}/repos/{tool.repo}/releases/latest")
    linked = re.search(r"https://github\.com/ggml-org/whisper\.cpp/releases/tag/(b\d+)", release.get("body") or "")
    tag = linked.group(1) if linked else release["tag_name"]
    if not re.fullmatch(r"b\d+|v\d+\.\d+\.\d+", tag):
        raise UpdateError(f"Unexpected upstream source release tag: {tag}")
    return tag


def process(tool: ToolSpec, destination: Path, temporary: Path, check_only: bool, force: bool = False) -> bool:
    tag = latest_source_tag(tool)
    commit = github.get_json(f"{github.API}/repos/{tool.repo}/commits/{tag}")["sha"]
    marker = destination / ".build_manifest.json"
    installed = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    current = (
        not force
        and installed.get("source_commit") == commit
        and all((destination / name).is_file() for name in ("whisper-cli.exe", "whisper-server.exe"))
    )
    print(f"Whisper {tag}: {commit}; {'current' if current else 'update available'}", flush=True)
    if current or check_only:
        return not current
    context = dict(require_native_execution("Whisper native build/install"))
    logs = project_cfg.component("asr/whispercpp").logs_dir / "builds" / str(time.time_ns())
    logs.mkdir(parents=True)
    print(f"[LOGS] {logs}", flush=True)
    manifest = {
        "repository": f"https://github.com/{tool.repo}",
        "release_tag": tag,
        "source_commit": commit,
        "execution_context": context,
    }
    env = visual_studio_environment()
    sdk = Path(env.get("VULKAN_SDK", ""))
    if not (sdk / "Bin/glslc.exe").is_file() or not (sdk / "Lib/vulkan-1.lib").is_file():
        raise UpdateError("Set VULKAN_SDK to an installed Windows Vulkan SDK")
    cmake = shutil.which("cmake", path=env.get("PATH"))
    ninja = shutil.which("ninja", path=env.get("PATH"))
    if not cmake or not ninja:
        raise UpdateError("CMake and Ninja are required in the Visual Studio build environment")
    additions = project_cfg.framework_install_dir(tool.source_checkout)
    source, build = additions / f"source-{tag}", additions / f"build-{tag}-vulkan"
    additions.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        run(
            ["git", "clone", "--depth", "1", "--branch", tag, f"https://github.com/{tool.repo}.git", str(source)],
            logs / "clone.log",
        )
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=30).strip()
    if actual != commit:
        raise UpdateError(f"Source checkout differs from release {tag}: {actual}")
    dirty = subprocess.check_output(["git", "-C", str(source), "diff", "--name-only"], text=True, timeout=30).strip()
    if dirty:
        raise UpdateError(f"Source has local changes; review before building: {dirty}")
    configure = [
        cmake,
        "-S",
        str(source),
        "-B",
        str(build),
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGGML_VULKAN=ON",
        "-DGGML_CUDA=OFF",
        "-DGGML_HIP=OFF",
        "-DGGML_NATIVE=ON",
        "-DWHISPER_BUILD_TESTS=OFF",
        "-DWHISPER_BUILD_EXAMPLES=ON",
        "-DWHISPER_BUILD_SERVER=ON",
        "-DWHISPER_BUILD_IS_DEV=OFF",
    ]
    run(configure, logs / "configure.log", env, 180)
    build_command = [cmake, "--build", str(build), "--target", "whisper-cli", "whisper-server", "--parallel", "6"]
    run(build_command, logs / "build.log", env)
    staged = temporary / "vulkan-package"
    staged.mkdir()
    for file in (build / "bin").iterdir():
        if file.suffix.lower() in (".exe", ".dll"):
            shutil.copy2(file, staged / file.name)
    for name in ("whisper-cli.exe", "whisper-server.exe", "ggml-vulkan.dll"):
        if not (staged / name).is_file():
            raise UpdateError(f"Build is missing {name}; see {logs}")
    manifest.update(
        backend="vulkan",
        vulkan_sdk=str(sdk),
        configure=configure,
        build=build_command,
        cmake_version=subprocess.check_output([cmake, "--version"], text=True).splitlines()[0],
    )
    (staged / ".build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    replace_installation(staged, destination)
    manifest["files_sha256"] = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in destination.iterdir()
        if file.suffix.lower() in (".exe", ".dll")
    }
    manifest["logs"] = str(logs)
    marker.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] {destination}", flush=True)
    return True
