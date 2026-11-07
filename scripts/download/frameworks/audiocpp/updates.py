"""AudioCpp releases and HIP build handlers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks import update_types as cfg
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec


def legacy_asset(directory: Path) -> str | None:
    readme = directory / "README-HIP.txt"
    if not readme.is_file():
        return None
    match = re.search(r"Windows HIP package \((rocm\d+\.\d+)\)", readme.read_text(encoding="utf-8"))
    return f"audiocpp-bin-win-hip-{match.group(1)}-x64.zip" if match else None


TOOLS = [
    ToolSpec(
        "audiocpp/vulkan",
        "audiocpp_server.exe",
        ReleaseType.DATE,
        repo="0xShug0/audio.cpp",
        # If the default Vulkan build fails on this CPU, switch to the portable asset pattern.
        asset_pattern=r"audio-.*-bin-windows-x64-vulkan\.zip$",
    ),
    ToolSpec(
        "audiocpp/rocm",
        "audiocpp_server.exe",
        ReleaseType.DATE,
        repo="0xShug0/audio.cpp",
        asset_pattern=r"^audio-.*-bin-windows-x64-rocm[\d.]+(?:-test)?\.zip$",
    ),
    ToolSpec(
        "audiocpp/additions/espeak-ng", "eSpeak NG/libespeak-ng.dll", ReleaseType.MANUAL, repo="espeak-ng/espeak-ng"
    ),
    ToolSpec("audiocpp/additions/mecab", "libmecab.dll", ReleaseType.MANUAL),
    ToolSpec(
        name=project_cfg.AUDIOCPP_ROCM_LEGACY_DIR.relative_to(project_cfg.FRAMEWORKS_DIR).as_posix(),
        repo="IIIIIllllIIIIIlllll/audio.cpp",
        exe="audiocpp_cli.exe",
        asset_pattern=r"^audiocpp-bin-win-hip-rocm7\.1-x64\.zip$",
        release_type=ReleaseType.DATE,
        in_use=False,
    ),
    ToolSpec(
        name=project_cfg.AUDIOCPP_ROCM_BUILD_DIR.relative_to(project_cfg.FRAMEWORKS_DIR).as_posix(),
        exe="audiocpp_server.exe",
        release_type=ReleaseType.BUILD,
        repo="0xShug0/audio.cpp",
        branch="main",
        source_checkout="audiocpp/additions/source",
        gpu_targets="gfx1101",
        in_use=False,
    ),
]


def find_audiocpp_rocm_path() -> Path:
    configured = os.environ.get("AUDIOCPP_ROCM_PATH")
    candidates = [Path(configured)] if configured else []
    installed = Path("C:\\Program Files\\AMD\\ROCm")
    if installed.is_dir():
        candidates.extend(sorted(installed.iterdir(), reverse=True))
    candidates.append(project_cfg.SDCPP_ROCM_SDK_BIN_DIR.parent)
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if any(
            (candidate / subpath).is_file() for subpath in (Path("bin/clang++.exe"), Path("lib/llvm/bin/clang++.exe"))
        ):
            return candidate.resolve()
    raise shared.UpdateError("ROCm HIP SDK/Clang was not found. Set AUDIOCPP_ROCM_PATH to its root directory.")


def find_audiocpp_vs_tools() -> tuple[Path, Path, Path]:
    vswhere = Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\Installer\\vswhere.exe")
    if not vswhere.is_file():
        raise shared.UpdateError("vswhere.exe was not found; install Visual Studio Build Tools with C++ support.")
    result = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    installation = Path(result.stdout.strip())
    vcvars = installation / "VC/Auxiliary/Build/vcvarsall.bat"
    msvc_dir = installation / "VC/Tools/MSVC"
    compatible_toolsets = sorted(msvc_dir.glob("14.44.*"), reverse=True) if msvc_dir.is_dir() else []
    cmake_dir = installation / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin"
    ninja_dir = installation / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja"
    if not vcvars.is_file() or not compatible_toolsets:
        raise shared.UpdateError("AudioCpp HIP builds require Visual Studio's MSVC 14.44 toolset and vcvarsall.bat.")
    if not (cmake_dir / "cmake.exe").is_file() or not (ninja_dir / "ninja.exe").is_file():
        raise shared.UpdateError("Visual Studio CMake and Ninja components are required for the AudioCpp HIP build.")
    return (vcvars, cmake_dir, ninja_dir)


def audiocpp_rocm_version(rocm_path: Path) -> str:
    for marker in (rocm_path / "bin/.hipVersion", rocm_path / ".hipVersion"):
        if marker.is_file():
            value = marker.read_text(encoding="utf-8", errors="replace").strip()
            if value:
                return value
    return rocm_path.name


def ensure_audiocpp_not_running(dest_dir: Path) -> None:
    shared.stop_installation_processes(dest_dir)


def package_audiocpp_hip(source_dir: Path, rocm_path: Path, staged: Path, manifest: dict[str, str]) -> None:
    import fnmatch

    build_bin = source_dir / "build/audiocpp-rocm-therock-10.2-hip-7.17-gfx1101/bin"
    for exe in ("audiocpp_server.exe", "audiocpp_cli.exe"):
        source_exe = build_bin / exe
        if not source_exe.is_file():
            raise shared.UpdateError(f"HIP build did not produce {source_exe}")
        shutil.copy2(source_exe, staged / exe)
    runtime_bin = rocm_path / "bin"
    patterns = (
        "amdhip64*.dll",
        "amd_comgr*.dll",
        "hipblas.dll",
        "libhipblas.dll",
        "hipblaslt.dll",
        "libhipblaslt.dll",
        "rocblas.dll",
    )
    copied_names: set[str] = set()
    for pattern in patterns:
        matches = sorted(
            (path for path in runtime_bin.rglob("*.dll") if fnmatch.fnmatch(path.name.lower(), pattern.lower())),
            key=lambda path: (len(path.parts), str(path).lower()),
        )
        if not matches:
            continue
        source_dll = matches[0]
        if source_dll.name.lower() not in copied_names:
            shutil.copy2(source_dll, staged / source_dll.name)
            copied_names.add(source_dll.name.lower())
    required_groups = (
        ("amdhip64",),
        ("amd_comgr",),
        ("hipblas.dll", "libhipblas.dll"),
        ("hipblaslt.dll", "libhipblaslt.dll"),
        ("rocblas.dll",),
    )
    for group in required_groups:
        if not any(
            filename.startswith(name) if name.startswith("amd") else filename == name
            for filename in copied_names
            for name in group
        ):
            raise shared.UpdateError(f"ROCm package is missing a required runtime DLL: {' or '.join(group)}")
    for folder in ("rocblas", "hipblaslt"):
        source_folder = runtime_bin / folder
        if not source_folder.is_dir():
            raise shared.UpdateError(f"ROCm package is missing its {folder} kernel directory")
        shutil.copytree(source_folder, staged / folder)
    previous_hip = project_cfg.AUDIOCPP_ROCM_LEGACY_DIR
    if not previous_hip.is_dir():
        previous_hip = project_cfg.FRAMEWORKS_DIR / "audiocpp"
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        crt = previous_hip / name
        if crt.is_file():
            shutil.copy2(crt, staged / name)
    (staged / "README-HIP.txt").write_text(
        f"audio.cpp Windows HIP build\nUpstream commit: {manifest['source_commit']}\nROCm: {manifest['rocm_version']}\nGPU targets: {manifest['gpu_targets']}\n",
        encoding="utf-8",
    )
    (staged / ".build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def install_audiocpp_hip(staged: Path, dest_dir: Path) -> None:
    ensure_audiocpp_not_running(dest_dir)
    backup: Path | None = None
    if dest_dir.exists():
        trash = project_cfg.BASE_DIR / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        backup = trash / f"audiocpp-hip-build-{time.strftime('%Y%m%d-%H%M%S')}"
        suffix = 1
        while backup.exists():
            backup = trash / f"audiocpp-hip-build-{time.strftime('%Y%m%d-%H%M%S')}-{suffix}"
            suffix += 1
        shutil.move(str(dest_dir), str(backup))
    try:
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest_dir))
    except Exception:
        if backup and backup.exists() and (not dest_dir.exists()):
            shutil.move(str(backup), str(dest_dir))
        raise


def process_audiocpp_hip(tool: cfg.ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool) -> bool:
    if not tool.repo or not tool.source_checkout or (not tool.gpu_targets):
        raise shared.UpdateError("AudioCpp HIP build entry is missing its source or GPU target configuration")
    source_dir = project_cfg.framework_install_dir(tool.source_checkout)
    source_tool = cfg.ToolSpec(
        name=tool.name, exe="", release_type=cfg.ReleaseType.SOURCE, repo=tool.repo, branch=tool.branch
    )
    if source_dir.exists():
        command = ["git", "-c", f"safe.directory={source_dir.as_posix()}", "-C", str(source_dir)]
        dirty = subprocess.run([*command, "status", "--porcelain"], capture_output=True, text=True, check=True)
        if dirty.stdout.strip():
            raise shared.UpdateError(
                f"AudioCpp source checkout has local changes; review it before building: {source_dir}"
            )
    latest_commit = shared.github.get_json(f"{shared.github.API}/repos/{tool.repo}/commits/{tool.branch}")["sha"]
    if check_only:
        commit = latest_commit
        shared.process_source(source_tool, source_dir, True)
    else:
        commit = shared.process_source(source_tool, source_dir, False)
        if commit != latest_commit:
            raise shared.UpdateError(
                "AudioCpp checkout did not land on the latest upstream commit; check for local commits or a concurrent upstream update before building."
            )
    rocm_path = find_audiocpp_rocm_path()
    rocm_version = audiocpp_rocm_version(rocm_path)
    manifest = {
        "repository": f"https://github.com/{tool.repo}",
        "source_commit": commit,
        "rocm_path": str(rocm_path),
        "rocm_version": rocm_version,
        "gpu_targets": tool.gpu_targets,
    }
    installed_manifest = dest_dir / ".build_manifest.json"
    installed = json.loads(installed_manifest.read_text(encoding="utf-8")) if installed_manifest.is_file() else None
    if installed == manifest and (dest_dir / tool.exe).is_file() and (dest_dir / "audiocpp_cli.exe").is_file():
        print(f"Status: UP TO DATE (source {commit[:12]}, ROCm {rocm_version})")
        return False
    print(f"ROCm root     : {rocm_path}")
    print(f"ROCm version  : {rocm_version}")
    print(f"GPU targets   : {tool.gpu_targets}")
    print(f"Built commit  : {(installed.get('source_commit', 'UNKNOWN') if installed else 'UNKNOWN')}")
    print(f"Latest commit : {commit}")
    if check_only:
        print("Status: HIP BUILD AVAILABLE")
        return True
    if not source_dir.is_dir():
        raise shared.UpdateError(f"AudioCpp source checkout was not created: {source_dir}")
    git = ["git", "-c", f"safe.directory={source_dir.as_posix()}", "-C", str(source_dir)]
    subprocess.run([*git, "submodule", "update", "--init", "--recursive"], check=True)
    vcvars, cmake_dir, ninja_dir = find_audiocpp_vs_tools()
    build_script = source_dir / "scripts/build_windows_hip.ps1"
    if not build_script.is_file():
        raise shared.UpdateError(f"Upstream HIP build script not found: {build_script}")
    build_dir = "build/audiocpp-rocm-therock-10.2-hip-7.17-gfx1101"
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    common = f'-NoProfile -ExecutionPolicy Bypass -File "{build_script}" -RocmPath "{rocm_path}" -GpuTargets "{tool.gpu_targets}" -BuildDir "{build_dir}" -NoNativeCpu -DeploymentBuild'
    batch_file = tmp_dir / "build-audiocpp-hip.cmd"
    batch_file.write_text(
        "\n".join(
            (
                "@echo off",
                f'call "{vcvars}" x64 -vcvars_ver=14.44 >nul',
                "if errorlevel 1 exit /b %errorlevel%",
                f'set "PATH={cmake_dir};{ninja_dir};%PATH%"',
                f'"{powershell}" {common} -Target audiocpp_server',
                "if errorlevel 1 exit /b %errorlevel%",
                f'"{powershell}" {common} -Target audiocpp_cli',
                "exit /b %errorlevel%",
                "",
            )
        ),
        encoding="utf-8",
    )
    print("Status: BUILDING UPSTREAM AUDIOCPP HIP PACKAGE")
    device_lib_path = rocm_path / "lib/llvm/amdgcn/bitcode"
    if not (device_lib_path / "ocml.bc").is_file() or not (device_lib_path / "ockl.bc").is_file():
        raise shared.UpdateError(f"ROCm device libraries were not found under {device_lib_path}")
    build_env = os.environ.copy()
    build_env["HIP_DEVICE_LIB_PATH"] = str(device_lib_path)
    subprocess.run(["cmd.exe", "/d", "/c", str(batch_file)], cwd=source_dir, env=build_env, check=True)
    staged = tmp_dir / "audiocpp-hip-stage"
    staged.mkdir()
    package_audiocpp_hip(source_dir, rocm_path, staged, manifest)
    install_audiocpp_hip(staged, dest_dir)
    print(f"Status: HIP BUILD INSTALLED (source {commit[:12]}, ROCm {rocm_version})")
    return True


def process_tool(
    tool: ToolSpec, destination: Path, temporary: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> None:
    needed = process_audiocpp_hip(tool, destination, temporary, check_only)
    if summary is not None:
        summary.record(tool, "available" if needed else "current")
