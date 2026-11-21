"""The rdna-boosts patch set, taken from a release tarball at a pinned tag instead of a branch.

The repo publishes the patch tree as `patches.tar.gz` beside `release.json` and a combined patch, and tags
every drop (`v17-4f9dfa0e3-r321`), so a build records the patch set it used. `release.json`'s `release` field
is the tag and its `base` is the llama.cpp commit to check out; it is a separate asset, because the tarball
holds only `patches/`.
"""

import json
import re
import shutil
from pathlib import Path

from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec

REPO = "stew675/llama-cpp-rdna-boosts"
# - the combined patch beside the tarball is one squashed file, which would lose the per-patch skip report
PATCH_ASSET = r"^patches\.tar\.gz$"
RELEASE_ASSET = r"^release\.json$"
RELEASE_JSON = "release.json"
TOOL = ToolSpec(
    "llamacpp/additions/llama-cpp-rdna-boosts",
    "",
    ReleaseType.PATCHES,
    repo=REPO,
    asset_pattern=PATCH_ASSET,
    # - the patch set only counts once the build that applies it exists
    rebuild_required=True,
)


def local_release(destination: Path) -> str | None:
    """The tag the installed patch set records, or None when nothing is installed."""
    marker = destination / RELEASE_JSON
    if not marker.is_file():
        return None
    release = json.loads(marker.read_text(encoding="utf-8")).get("release")
    return str(release) if release else None


def asset_named(release: shared.Release, pattern: str) -> shared.Asset:
    """The one asset of a release whose name matches, named by the pattern that selected it."""
    asset = next((item for item in release["assets"] if re.search(pattern, item["name"])), None)
    if asset is None:
        raise shared.UpdateError(f"{release['tag_name']} has no asset matching {pattern}")
    return asset


def install(release: shared.Release, destination: Path, temporary: Path) -> None:
    """Unpack `patches/` and place the `release.json` that names it, in one staged tree."""
    archive = shared.download_asset(asset_named(release, PATCH_ASSET), temporary)
    metadata = shared.download_asset(asset_named(release, RELEASE_ASSET), temporary)
    staged = shared.staging_directory(temporary, prefix="rdna-patches-")
    # - the tarball holds `patches/` at its root with no wrapper folder, so it is installed as shipped
    shutil.unpack_archive(str(archive), str(staged))
    if not (staged / "patches").is_dir():
        raise shared.UpdateError("rdna-boosts patch tarball has no patches/ folder")
    shutil.copy2(metadata, staged / RELEASE_JSON)
    shared.replace_installation(staged, destination)


def process_tool(
    tool: ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> None:
    """Compare the installed patch set with the newest release, then install it unless this is a check."""
    release, _asset = shared.get_release(tool)
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
    install(release, dest_dir, tmp_dir)
    print("Status: UPDATED")


def ensure(destination: Path, temporary: Path) -> None:
    """Install the newest patch set where a build needs one, whatever the catalog reports."""
    process_tool(TOOL, destination, temporary, False, None)
