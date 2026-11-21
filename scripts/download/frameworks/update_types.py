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
    BUILD = "build"
    NATIVE_BUILD = "native-build"
    WHEEL = "wheel"
    SDK = "sdk"
    PATCHES = "patches"
    STRATA = "strata"
    DESKTOP = "desktop"
    # - the vendor's own app owns the install; a check would only restate its updater
    APP_UPDATER = "app-updater"
    # - a file placed by hand with no feed to compare; nothing here can check it
    HAND_INSTALL = "hand-install"


# - how an update replaces files on disk; the summary nests status under these, in this order
UPDATE_KINDS = (
    "git fast-forward",
    "github release",
    "npm package",
    "app installer",
    "app updater",
    "vendor script",
    "git snapshot",
    "pip wheel",
    "local build",
    "hand install",
)
KIND_OF_RELEASE = {
    ReleaseType.SOURCE: "git fast-forward",
    ReleaseType.RELEASE: "github release",
    ReleaseType.PRERELEASE: "github release",
    ReleaseType.DATE: "github release",
    ReleaseType.NPM: "npm package",
    ReleaseType.DESKTOP: "app installer",
    ReleaseType.STRATA: "app installer",
    ReleaseType.APP_UPDATER: "app updater",
    ReleaseType.BAT: "vendor script",
    ReleaseType.SNAPSHOT: "git snapshot",
    ReleaseType.WHEEL: "pip wheel",
    ReleaseType.SDK: "pip wheel",
    ReleaseType.PATCHES: "github release",
    ReleaseType.BUILD: "local build",
    ReleaseType.NATIVE_BUILD: "local build",
    ReleaseType.HAND_INSTALL: "hand install",
}
UNCLASSIFIED_KIND = "unclassified"


def update_kind(tool: "ToolSpec") -> str:
    """The kind that updates this entry; a compile it must finish first is its own kind."""
    return "local build" if tool.rebuild_required else KIND_OF_RELEASE.get(tool.release_type, UNCLASSIFIED_KIND)


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
