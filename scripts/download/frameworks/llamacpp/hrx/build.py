"""Merge, incrementally build, validate and optionally install HRX with rollback."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.paths import dated_run
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import native_build
from scripts.download.frameworks.framework_catalog import hrx_tools
from scripts.download.frameworks.llamacpp.hrx import prepare as prepare_hrx
from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.tests.shared.paths import RunPaths

HRX_ROOT = project_cfg.FRAMEWORKS_DIR / "llamacpp" / "additions" / "hrx"


def run_step(name: str, command: list[str], paths: RunPaths, env: dict[str, str] | None = None) -> None:
    started = time.monotonic()
    log = paths.logs / f"{name}.log"
    print(f"[BUILD] {name} -> {log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=project_cfg.BASE_DIR, env=env, stdout=stream, stderr=subprocess.STDOUT)
        try:
            launch_util.assign_process_to_job(process.pid)
            while True:
                try:
                    code = process.wait(timeout=20)
                    break
                except subprocess.TimeoutExpired:
                    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
                    print(
                        f"[BUILD] {name}: {time.monotonic() - started:.0f}s; {lines[-1] if lines else 'running'}",
                        flush=True,
                    )
        except BaseException:
            launch_util.kill_process_tree(process.pid)
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            raise
    if code:
        raise RuntimeError(f"{name} failed ({code}); see {log}")
    print(f"[OK] {name}: {time.monotonic() - started:.1f}s", flush=True)


def stale_cache_message(directory: Path) -> str | None:
    """A cache recorded under another path makes CMake refuse to configure; name the fix."""
    cache = directory / "CMakeCache.txt"
    if not cache.is_file():
        return None
    match = re.search(
        r"^CMAKE_CACHEFILE_DIR:INTERNAL=(.+)$", cache.read_text(encoding="utf-8", errors="replace"), re.MULTILINE
    )
    recorded = match.group(1).strip().replace("\\", "/") if match else ""
    if recorded and Path(recorded).resolve() != directory.resolve():
        return f"Build cache in {directory} was created at {recorded}; remove that directory to rebuild here."
    return None


MIN_CMAKE = (4, 2)


def cmake_path() -> str:
    """The installed CMake; a Windows HRX build needs 4.2 or newer for short object names."""
    executable = shutil.which("cmake")
    if executable is None:
        raise RuntimeError("CMake is not on PATH; install 4.2 or newer before building HRX")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", version)
    if not match or (int(match.group(1)), int(match.group(2))) < MIN_CMAKE:
        raise RuntimeError(f"{version.splitlines()[0]} is too old; HRX on Windows needs CMake 4.2 or newer")
    return executable


def configured(cache: Path) -> bool:
    """True when the HRX cache carries the options the current upstream requires."""
    if not cache.is_file():
        return False
    text = cache.read_text(encoding="utf-8", errors="replace")
    return all(
        re.search(rf"^{name}:[A-Z]+=ON$", text, re.MULTILINE)
        for name in ("LOOM_TARGET_VM", "LOOM_TARGET_ARCH_VM", "AMDF_BUILD")
    )


def configure(cmake: str, paths: RunPaths) -> None:
    """Configure the HRX tree as the current upstream expects, inside the Visual Studio environment."""
    run_step(
        "hrx-configure",
        [
            cmake,
            "-S",
            str(HRX_ROOT / "hrx-system"),
            "-B",
            str(HRX_ROOT / "build/hrx"),
            "-DLOOM_TARGET_VM=ON",
            "-DLOOM_TARGET_ARCH_VM=ON",
            "-DAMDF_BUILD=ON",
            f"-DIREE_ROCM_PATH={project_cfg.ROCM_SDK_BIN_DIR.parent}",
            f"-DPython3_EXECUTABLE={sys.executable}",
        ],
        paths,
        native_build.visual_studio_environment(),
    )


def build(paths: RunPaths, jobs: int) -> None:
    for name in ("rocr", "hrx", "llamacpp"):
        directory = HRX_ROOT / "build" / name
        if message := stale_cache_message(directory):
            raise RuntimeError(message)
        if not directory.is_dir():
            raise RuntimeError(f"{directory} is not configured; see the HRX note in UPDATES.md")
    cmake = cmake_path()
    if not configured(HRX_ROOT / "build/hrx/CMakeCache.txt"):
        configure(cmake, paths)

    def compile_targets(directory: str, targets: list[str]) -> list[str]:
        return [
            cmake,
            "--build",
            str(HRX_ROOT / "build" / directory),
            "--config",
            "Release",
            "--target",
            *targets,
            "--parallel",
            str(jobs),
        ]

    # - every step runs inside the Visual Studio environment: a configure re-run needs cl and ml64
    env = native_build.visual_studio_environment()
    run_step("rocr-build", compile_targets("rocr", ["hsa-runtime64"]), paths, env)
    # - Current upstream's descriptor generators consume this file without a reliable VS build-order edge.
    run_step(
        "hrx-contracts", compile_targets("hrx", ["loom_target_arch_amdgpu_contracts_contract_tables_gen"]), paths, env
    )
    run_step(
        "hrx-build",
        compile_targets(
            "hrx",
            [
                "hrx",
                "loomc_shared",
                "libhrx_tools_hrx-info",
                "loom_tools_loom-format_loom-format",
                "loom_tools_loom-link_loom-link",
            ],
        ),
        paths,
        env,
    )
    run_step(
        "hrx-stage",
        [cmake, "--install", str(HRX_ROOT / "build/hrx"), "--config", "Release", "--component", "HrxPublicDist"],
        paths,
        env,
    )
    run_step("llama-build", compile_targets("llamacpp", ["llama-server", "llama-cli", "test-backend-ops"]), paths, env)


def merge_sources(paths: RunPaths) -> None:
    for tool in hrx_tools():
        source = project_cfg.FRAMEWORKS_DIR / tool.name
        command = ["git", "-C", str(source)]
        status = subprocess.check_output([*command, "status", "--porcelain"], text=True).strip()
        if status:
            raise RuntimeError(f"Preserve and commit local changes before merging {source}:\n{status}")
        run_step(f"fetch-{source.name}", [*command, "fetch", "origin", tool.branch], paths)
        run_step(f"merge-{source.name}", [*command, "merge", "--no-edit", "--no-stat", "origin/" + tool.branch], paths)


def stage_candidate(paths: RunPaths) -> Path:
    from scripts.benchmarks.llamacpp.hrx import hrx_tensor_probe

    candidate = paths.temp / "bin"
    hrx_tensor_probe.build(candidate)
    checkpoint = json.loads((HRX_ROOT / "runtime/checkpoint.json").read_text(encoding="utf-8"))
    special = {
        "hrx.dll": HRX_ROOT / "build/hrx/libhrx/src/libhrx/Release/hrx.dll",
        "loomc.dll": HRX_ROOT / "build/hrx/loom/binding/c/Release/loomc.dll",
        "hsa-runtime64.dll": HRX_ROOT / "build/rocr/rocr/runtime/Release/hsa-runtime64.dll",
    }
    for name in checkpoint["sha256"]:
        if name != "hrx-tensor-probe.exe":
            source = special[name] if name in special else HRX_ROOT / "build/llamacpp/bin/Release" / name
            shutil.copy2(source, candidate / name)
    for source in (
        HRX_ROOT / "build/llamacpp/bin/Release/test-backend-ops.exe",
        HRX_ROOT / "build/hrx/libhrx/tools/Release/hrx-info.exe",
    ):
        shutil.copy2(source, candidate / source.name)
    hashes = {}
    for name in checkpoint["sha256"]:
        with (candidate / name).open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    (paths.artifacts / "candidate-binaries.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    return candidate


def install_candidate(paths: RunPaths) -> Path:
    from scripts.tests.cases.llamacpp.hrx import hrx_update_validation

    checks = hrx_update_validation.verify_candidate_evidence(paths)
    hrx_update_validation.record_sources(paths)
    runtime = cfg.LLAMACPP_BUILDS["hrx"].bin_dir
    previous = json.loads((runtime / "checkpoint.json").read_text(encoding="utf-8"))
    prepare_hrx.verify_hashes(runtime, previous["sha256"])
    verified = paths.root.parent.parent / "verified" / paths.root.name
    if verified.exists():
        raise FileExistsError(f"Preserve the existing checkpoint; choose a new run directory: {verified}")
    verified.mkdir(parents=True)
    shutil.copytree(paths.artifacts, verified / "artifacts")
    shutil.copytree(paths.logs, verified / "logs")
    backup = verified / "temp/previous-runtime"
    backup.parent.mkdir(parents=True)
    shutil.copytree(runtime, backup)
    binaries = verified / "temp/bin"
    binaries.mkdir()
    for name in checks["hashes"]:
        shutil.copy2(paths.temp / "bin" / name, binaries / name)
    (verified / "artifacts/binaries.json").write_text(json.dumps(checks["hashes"], indent=2), encoding="utf-8")
    (verified / "artifacts/previous-checkpoint.json").write_text(json.dumps(previous, indent=2), encoding="utf-8")
    try:
        prepare_hrx.install_checkpoint(verified)
        verified_paths = RunPaths(verified)
        run_step(
            "installed-performance",
            [sys.executable, "-m", "scripts.benchmarks.llamacpp.hrx.hrx_performance", "--runtime", str(runtime)],
            verified_paths,
        )
        installed = hrx_update_validation.verify_installed_runtime(verified_paths)
    except BaseException:
        prepare_hrx.restore_backup(backup)
        raise
    write_checkpoint_report(verified_paths)
    print(f"[OK] Installed HRX checkpoint: {verified}; decode {installed['speeds']}", flush=True)
    return verified


def write_checkpoint_report(paths: RunPaths) -> None:
    installed = json.loads((paths.artifacts / "installed-validation.json").read_text(encoding="utf-8"))
    previous = json.loads((paths.artifacts / "previous-checkpoint.json").read_text(encoding="utf-8"))
    paths.write_report(
        {
            "name": "HRX runtime update",
            "category": "probes",
            "status": "passed",
            "reasoning": "Six CPU-reference operators, normal/chunked tensors, exact code tokens/text, chat, installed "
            "binary hashes and generation passed. Previous runtime retained for rollback; ports clear. "
            "Validation covers short Swift requests at 8K/f16 KV; other models and larger contexts remain "
            "unverified.",
            "installed": installed,
            "previous_checkpoint": previous,
            "provenance": provenance.block(
                subject="HRX runtime update",
                config={"previous_checkpoint": previous},
                frameworks=[provenance.framework_state("llamacpp")],
                models=[],
            ),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="Evidence directory; defaults to a fresh HRX update run")
    parser.add_argument(
        "--validate-only", action="store_true", help="Stage and fully validate the existing build outputs"
    )
    parser.add_argument(
        "--merge", action="store_true", help="Fetch and merge upstream, stopping on dirty checkouts or conflicts"
    )
    parser.add_argument("--install", action="store_true", help="Run full correctness checks and install with rollback")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    if args.merge and args.validate_only:
        parser.error("--merge requires rebuilding; omit --validate-only")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if launch_util.llama_server_running():
        raise RuntimeError("A configured llama-server is running; stop or confirm session safety before proceeding")
    run_dir = (
        args.run_dir.resolve()
        if args.run_dir
        else dated_run(project_cfg.TEST_OUTPUT_DIR / "probes/hrx_updates/unreviewed")
    )
    paths = RunPaths(run_dir)
    paths.create()
    if args.merge:
        merge_sources(paths)
    if not args.validate_only:
        build(paths, args.jobs)
    candidate = stage_candidate(paths)
    env = os.environ.copy()
    env.update(
        ROCR_VISIBLE_DEVICES="1", ROCR_USE_PM4="1", IREE_HAL_AMDGPU_LIBHSA_PATH=str(candidate / "hsa-runtime64.dll")
    )
    env.pop("HSA_OVERRIDE_GFX_VERSION", None)
    run_step("discovery", [str(candidate / "hrx-info.exe"), "--device=gpu:0"], paths, env)
    run_step(
        "performance",
        [sys.executable, "-m", "scripts.benchmarks.llamacpp.hrx.hrx_performance", "--runtime", str(candidate)],
        paths,
    )
    from scripts.tests.cases.llamacpp.hrx import hrx_update_validation

    hrx_update_validation.validate_candidate(paths)
    hrx_update_validation.record_sources(paths)
    print(f"[OK] Full candidate validation passed: {candidate}", flush=True)
    if args.install:
        install_candidate(paths)
    else:
        print("[NEXT] Use --install to install after validation with automatic rollback.", flush=True)


if __name__ == "__main__":
    main()
