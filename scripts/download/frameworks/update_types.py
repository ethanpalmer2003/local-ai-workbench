"""Shared catalog types; no installation side effects."""

from dataclasses import dataclass
from enum import Enum


class ReleaseType(str, Enum):
    PRERELEASE = "prerelease"
    RELEASE = "release"
    DATE = "date"
    BAT = "bat"
    NPM = "npm"
    SOURCE = "source"
    SNAPSHOT = "snapshot"
    MANUAL = "manual"
    BUILD = "build"
    NATIVE_BUILD = "native-build"
    WHEEL = "wheel"
    STRATA = "strata"
    DESKTOP = "desktop"


# - how an update replaces files on disk; the summary nests status under these, in this order
UPDATE_KINDS = (
    "git fast-forward",
    "github release",
    "npm package",
    "app installer",
    "vendor script",
    "git snapshot",
    "pip wheel",
    "local build",
    "manual",
)
KIND_OF_RELEASE = {
    ReleaseType.SOURCE: "git fast-forward",
    ReleaseType.RELEASE: "github release",
    ReleaseType.PRERELEASE: "github release",
    ReleaseType.DATE: "github release",
    ReleaseType.NPM: "npm package",
    ReleaseType.DESKTOP: "app installer",
    ReleaseType.STRATA: "app installer",
    ReleaseType.BAT: "vendor script",
    ReleaseType.SNAPSHOT: "git snapshot",
    ReleaseType.WHEEL: "pip wheel",
    ReleaseType.BUILD: "local build",
    ReleaseType.NATIVE_BUILD: "local build",
    ReleaseType.MANUAL: "manual",
}
UNCLASSIFIED_KIND = "unclassified"


def update_kind(tool: "ToolSpec") -> str:
    return KIND_OF_RELEASE.get(tool.release_type, UNCLASSIFIED_KIND)


@dataclass
class ToolSpec:
    name: str
    exe: str
    release_type: ReleaseType
    repo: str | None = None
    asset_pattern: str | None = None
    # - per-tool local-version regex, applied to the exe's --version output
    version_regex: str | None = None
    version_prefix: str = ""
    # - update coverage only; does not disable manual launchers
    in_use: bool = True
    package: str | None = None
    branch: str = "main"
    install_subdir: str = ""
    manual_merge: bool = False
    rebuild_required: bool = False
    # - one local patch commit is replayed with `pull --rebase` instead of blocking the update
    rebase_local: bool = False
    # - Electron "generic" feed; `channel` names <channel>.yml under it
    feed: str = ""
    channel: str = "latest"
    # - argv recompiled by hand in the install directory after a source update
    build_command: tuple[str, ...] = ()
    source_path: str = ""
    source_checkout: str = ""
    gpu_targets: str = ""
    category: str = "other"
    # - summary line this entry is reported under; empty means its own name
    group: str = ""
    # - folder whose direct child git checkouts are compared with their own origin
    tracked_checkouts: str = ""
