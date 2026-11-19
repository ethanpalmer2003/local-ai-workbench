"""The rdna-boosts patch set, taken from a release tarball at a pinned tag instead of a branch.

The repo publishes `patches/` plus `release.json` as `patches.tar.gz` beside a combined patch and a
`SHA256SUMS` file, and tags every drop (`v17-4f9dfa0e3-r321`), so a build records the patch set it used.
`release.json`'s `release` field is the tag and its `base` is the llama.cpp commit to check out.
"""

import json
import shutil
from pathlib import Path

from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec

REPO = "stew675/llama-cpp-rdna-boosts"
# - the combined patch beside it is one squashed file, which would lose the per-patch skip report
PATCH_ASSET = r"^patches\.tar\.gz$"
RELEASE_JSON = "release.json"
TOOL = ToolSpec(
    "llamacpp/additions/llama-cpp-rdna-boosts", "", ReleaseType.PATCHES, repo=REPO, asset_pattern=PATCH_ASSET
)


def local_release(destination: Path) -> str | None:
    """The tag the installed patch set records, or None when nothing is installed."""
    marker = destination / RELEASE_JSON
    if not marker.is_file():
        return None
    release = json.loads(marker.read_text(encoding="utf-8")).get("release")
    return str(release) if release else None


def install(asset: shared.Asset, destination: Path, temporary: Path, exe_name: str) -> None:
    """Unpack the patch tarball, keeping the layout of the tree it ships."""
    archive = shared.download_asset(asset, temporary)
    staged = shared.staging_directory(temporary, prefix="rdna-patches-")
    shutil.unpack_archive(str(archive), str(staged))
    entries = list(staged.iterdir())
    # - a GitHub tarball wraps its tree in one folder, and that folder is the patch set
    if len(entries) == 1 and entries[0].is_dir():
        staged = entries[0]
    if not (staged / RELEASE_JSON).is_file():
        raise shared.UpdateError(f"rdna-boosts release has no {RELEASE_JSON}")
    shared.replace_installation(staged, destination)


def process_tool(
    tool: ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> None:
    """Compare the installed patch set with the newest release, then install it unless this is a check."""
    release, asset = shared.get_release(tool)
    local = local_release(dest_dir)
    print(f"Local release : {local or 'NOT INSTALLED'}")
    print(f"Latest release: {release['tag_name']}")
    if local == release["tag_name"]:
        print("Status: UP TO DATE")
        if summary is not None:
            summary.record(tool, "current")
        return
    print("Status: UPDATE AVAILABLE")
    if summary is not None:
        summary.record(tool, "available")
    if check_only:
        return
    install(asset, dest_dir, tmp_dir, tool.exe)
    print("Status: UPDATED")


def ensure(destination: Path, temporary: Path) -> None:
    """Install the newest patch set where a build needs one, whatever the catalog reports."""
    process_tool(TOOL, destination, temporary, False, None)
