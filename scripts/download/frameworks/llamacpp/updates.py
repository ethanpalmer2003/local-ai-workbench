"""llama.cpp release, source and support-tool catalog."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from scripts.download.frameworks.update_types import ReleaseType, ToolSpec
from scripts.config import project_config as project_cfg
from scripts.download.frameworks import update_shared as shared


def source_dirty(
    tool: ToolSpec, directory: Path, local: str, latest: str, check_only: bool, summary: shared.UpdateSummary | None
) -> bool:
    if not tool.name.startswith("llamacpp/additions/hrx/"):
        return False
    command = ["git", "-c", f"safe.directory={directory.as_posix()}", "-C", str(directory)]
    dirty = subprocess.run([*command, "status", "--porcelain"], capture_output=True, text=True, check=True)
    if not dirty.stdout.strip():
        return False
    if local == latest:
        if summary is not None:
            summary.record(tool, "current", "local patches retained")
        print("Status: SOURCE UP TO DATE (local patches retained)")
    else:
        shared.report_rebuild(tool, summary)
        if summary is not None:
            summary.patch_sources.append((tool, directory, latest))
        if not check_only:
            folder = shared.snapshot_source_patches(tool, directory, local, latest, dirty.stdout)
            print(f"Patch snapshot: {folder}")
    return True


def source_ahead(tool: ToolSpec, directory: Path) -> bool:
    if not tool.name.startswith("llamacpp/additions/hrx/"):
        return False
    command = ["git", "-c", f"safe.directory={directory.as_posix()}", "-C", str(directory)]
    result = subprocess.run(
        [*command, "rev-list", "--count", f"origin/{tool.branch}..HEAD"], capture_output=True, text=True, check=True
    )
    return int(result.stdout.strip()) > 0


def release_notes(release: shared.Release) -> None:
    rocm = re.search(r"\*\*ROCm Version\*\*:\s*([^\r\n]+)", release.get("body") or "")
    print(f"Latest ROCm: {rocm.group(1).strip() if rocm else 'UNKNOWN (release notes omit version)'}")


def hrx_tools() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            "llamacpp/additions/hrx/llama.cpp",
            "",
            ReleaseType.SOURCE,
            repo="AMD-Ecosystem/llama.cpp",
            branch="hrx-graph-develop-v2",
            in_use=False,
        ),
        ToolSpec("llamacpp/additions/hrx/hrx-system", "", ReleaseType.SOURCE, repo="ROCm/hrx-system", in_use=False),
        ToolSpec(
            "llamacpp/additions/hrx/rocm-systems",
            "",
            ReleaseType.SOURCE,
            repo="ROCm/rocm-systems",
            branch="develop",
            in_use=False,
        ),
    )


def rdna_tools() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            "llamacpp/rdna",
            "",
            ReleaseType.SOURCE,
            repo="ggml-org/llama.cpp",
            branch="master",
            manual_merge=True,
            in_use=False,
        ),
        ToolSpec(
            "llamacpp/additions/llama-cpp-rdna-boosts",
            "",
            ReleaseType.SOURCE,
            repo="stew675/llama-cpp-rdna-boosts",
            in_use=False,
        ),
    )


TOOLS = [
    *hrx_tools(),
    ToolSpec(
        "llamacpp/rocm/stock",
        "llama-cli.exe",
        ReleaseType.PRERELEASE,
        in_use=False,
        repo="ggml-org/llama.cpp",
        asset_pattern=r"llama-.*-bin-win-rocm-\d+\.\d+-x64\.zip",
        version_regex=r"build (\d+)",
        version_prefix="b",
    ),
    ToolSpec(
        "llamacpp/vulkan",
        "llama-cli.exe",
        ReleaseType.PRERELEASE,
        repo="ggml-org/llama.cpp",
        asset_pattern=r"llama-.*-bin-win-vulkan-x64\.zip",
        version_regex=r"build (\d+)",
        version_prefix="b",
    ),
    *rdna_tools(),
    ToolSpec(
        "llamacpp/additions/sccache",
        "sccache.exe",
        ReleaseType.RELEASE,
        repo="mozilla/sccache",
        asset_pattern=r"^sccache-v.*-x86_64-pc-windows-msvc\.zip$",
        version_regex=r"sccache (\d+\.\d+\.\d+)",
        version_prefix="v",
        install_subdir="bin",
    ),
    ToolSpec(
        name="llamacpp/rocm/lemonade",
        repo="lemonade-sdk/llamacpp-rocm",
        exe="llama-cli.exe",
        asset_pattern=r"llama-.*-windows-rocm-gfx110X-x64\.zip",
        release_type=ReleaseType.DATE,
    ),
]


def snapshot_source_patches(tool: ToolSpec, dest_dir: Path, local: str, latest: str, status: str) -> Path:
    command = ["git", "-c", f"safe.directory={dest_dir.as_posix()}", "-C", str(dest_dir)]
    patch_bytes = subprocess.run([*command, "diff", "--binary", "HEAD"], capture_output=True, check=True).stdout
    folder = (
        project_cfg.component("llamacpp").state_dir / "hrx" / "source-patches" / str(time.time_ns()) / dest_dir.name
    )
    folder.mkdir(parents=True)
    (folder / "local.patch").write_bytes(patch_bytes)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "repo": tool.repo,
                "branch": tool.branch,
                "source": str(dest_dir),
                "base": local,
                "upstream": latest,
                "status": status,
                "untracked_files": "remain in the source checkout",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return folder
