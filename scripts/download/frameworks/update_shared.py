"""Shared release/source operations and check-first update planning."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TextIO, TypedDict, cast

import requests

if TYPE_CHECKING:
    import psutil

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import github
from scripts.download.frameworks import update_types as cfg
from scripts.file_util import archive_path

MARKER_NAME = ".release_published_at"
ASSET_MARKER_NAME = ".release_asset"
CATEGORY_HEADINGS = (("llamacpp", "LLAMA.CPP"), ("speech", "TTS / ASR"), ("asr", "ASR"), ("other", "OTHER"))
# - these name the exact entry; collapsing them would hide which one broke
EXPANDED_STATUSES = ("CHECK FAILED", "SKIPPED BY OPTION")


class Asset(TypedDict):
    name: str
    browser_download_url: str
    digest: NotRequired[str | None]


class Release(TypedDict):
    assets: list[Asset]
    tag_name: str
    published_at: str
    prerelease: bool
    body: NotRequired[str | None]


class UpdateError(Exception):
    pass


def tool_label(tool: cfg.ToolSpec) -> str:
    return f"{tool.name} ({tool.package})" if tool.package else tool.name


@dataclass
class UpdateSummary:
    current: list[str] = field(default_factory=list)
    available: list[str] = field(default_factory=list)
    package_sync: list[str] = field(default_factory=list)
    manual_rebuild: list[str] = field(default_factory=list)
    source_build: list[str] = field(default_factory=list)
    manual_check: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    apply_keys: set[str] = field(default_factory=set)
    patch_sources: list[tuple[cfg.ToolSpec, Path, str]] = field(default_factory=list)
    categories: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    group_keys: dict[str, str] = field(default_factory=dict)

    def groups(self) -> tuple[tuple[str, list[str]], ...]:
        return (
            ("UP TO DATE", self.current),
            ("UPDATE AVAILABLE", self.available),
            ("PI PACKAGE SYNC REQUIRED", self.package_sync),
            ("UPSTREAM CHANGED; MANUAL MERGE/REBUILD REQUIRED", self.manual_rebuild),
            ("SOURCE UPDATE AVAILABLE; BUILD REQUIRED", self.source_build),
            ("MANUAL CHECK/UPDATE REQUIRED", self.manual_check),
            ("CHECK FAILED", self.failures),
            ("SKIPPED BY OPTION", self.skipped),
        )

    def record(self, tool: cfg.ToolSpec, group: str, detail: str = "", actionable: bool = False) -> None:
        label = tool_label(tool)
        self.categories[label] = tool.category
        self.kinds[label] = cfg.update_kind(tool)
        # - one line per component: pi packages, command-code CLI and desktop, Strata parts
        self.group_keys[label] = tool.group or tool.name
        getattr(self, group).append(label + (f" :: {detail}" if detail else ""))
        if group == "available" or actionable:
            self.apply_keys.add(label)

    def discard(self, tool: cfg.ToolSpec) -> None:
        label = tool_label(tool)
        for _, names in self.groups():
            names[:] = [name for name in names if name != label and not name.startswith(label + " ::")]
        self.apply_keys.discard(label)
        self.group_keys.pop(label, None)
        self.kinds.pop(label, None)
        self.patch_sources[:] = [entry for entry in self.patch_sources if tool_label(entry[0]) != label]

    def summarize(self, names: list[str], grouped: bool = True, blocked: frozenset[str] = frozenset()) -> list[str]:
        """Collapse per-package and per-part entries onto their component's line."""
        details: dict[str, list[str]] = {}
        for entry in names:
            label, _, detail = entry.partition(" :: ")
            key = self.group_keys.get(label, label)
            if not grouped or key in blocked:
                key = label
            bucket = details.setdefault(key, [])
            if detail and detail not in bucket:
                bucket.append(detail)
        return [f"- {key}: {'; '.join(items)}" if items else f"- {key}" for key, items in details.items()]

    def failed_groups(self) -> frozenset[str]:
        """Groups with at least one failure stay expanded so the broken entry is visible."""
        keys = set()
        for entry in self.failures:
            label = entry.partition(" :: ")[0]
            keys.add(self.group_keys.get(label, label))
        return frozenset(keys)

    def _in_category(self, entry: str, category: str) -> bool:
        return self.categories.get(entry.partition(" :: ")[0], "other") == category

    def kinds_present(self, category: str) -> list[str]:
        seen = {
            self.kinds.get(entry.partition(" :: ")[0], cfg.UNCLASSIFIED_KIND)
            for _, names in self.groups()
            for entry in names
            if self._in_category(entry, category)
        }
        return [kind for kind in (*cfg.UPDATE_KINDS, cfg.UNCLASSIFIED_KIND) if kind in seen]

    def status_sections(self, category: str, kind: str) -> list[tuple[str, list[str]]]:
        return [
            (
                title,
                [
                    entry
                    for entry in names
                    if self._in_category(entry, category)
                    and self.kinds.get(entry.partition(" :: ")[0], cfg.UNCLASSIFIED_KIND) == kind
                ],
            )
            for title, names in self.groups()
        ]

    def split_groups(self, category: str) -> frozenset[str]:
        """A component whose parts update by different rules is expanded, so no line repeats."""
        kinds: dict[str, set[str]] = {}
        for _, names in self.groups():
            for entry in names:
                label = entry.partition(" :: ")[0]
                if self._in_category(label, category):
                    kinds.setdefault(self.group_keys.get(label, label), set()).add(
                        self.kinds.get(label, cfg.UNCLASSIFIED_KIND)
                    )
        return frozenset(key for key, seen in kinds.items() if len(seen) > 1)

    def print(self) -> None:
        for category, heading in CATEGORY_HEADINGS:
            kinds = self.kinds_present(category)
            if not kinds:
                continue
            print(f"\n=== {heading} ===")
            blocked = self.failed_groups() | self.split_groups(category)
            for kind in kinds:
                print(f"\n--- {kind} ---")
                for title, names in self.status_sections(category, kind):
                    if not names:
                        continue
                    print(f"\n[{title}]")
                    for line in self.summarize(
                        list(dict.fromkeys(names)), grouped=title not in EXPANDED_STATUSES, blocked=blocked
                    ):
                        print(line)


ManagedHandler = Callable[[cfg.ToolSpec, Path, Path, bool, UpdateSummary | None], None]
ReleaseInstaller = Callable[[Asset, Path, Path, str], None]
MANAGED_HANDLERS: dict[cfg.ReleaseType, ManagedHandler] = {}
RELEASE_INSTALLERS: dict[cfg.ReleaseType, ReleaseInstaller] = {}
# - per-tool post-install steps; they also run on apply when the download is already current.
POST_INSTALLERS: dict[str, Callable[[cfg.ToolSpec], None]] = {}
# - a post-install step also runs on apply when its tool has no update, but only while
#   this predicate says the step still has work; otherwise a no-update run stays silent.
POST_INSTALL_PENDING: dict[str, Callable[[cfg.ToolSpec], bool]] = {}


SOURCE_PATCH_WRITER: Callable[[cfg.ToolSpec, Path, str, str, str], Path] | None = None
SOURCE_DIRTY_CHECK: Callable[[cfg.ToolSpec, Path, str, str, bool, UpdateSummary | None], bool] | None = None
SOURCE_AHEAD_CHECK: Callable[[cfg.ToolSpec, Path], bool] | None = None
SNAPSHOT_MODIFIERS: dict[str, Callable[[Path], list[str]]] = {}
ASSET_FALLBACKS: dict[str, Callable[[Path], str | None]] = {}
RELEASE_NOTES: dict[str, Callable[[Release], None]] = {}


def report_rebuild(tool: cfg.ToolSpec, summary: UpdateSummary | None) -> None:
    if summary is None:
        print("Status: UPSTREAM CHANGED; MANUAL MERGE/REBUILD REQUIRED")
    else:
        summary.record(tool, "manual_rebuild")


def report_source_build(tool: cfg.ToolSpec, summary: UpdateSummary | None) -> None:
    """A clean checkout the updater may fast-forward, still compiled by hand afterwards."""
    if summary is None:
        print("Status: SOURCE UPDATE AVAILABLE; BUILD REQUIRED")
    else:
        summary.record(tool, "source_build", actionable=True)


def report_local_changes(tool: cfg.ToolSpec, summary: UpdateSummary | None) -> None:
    """Local edits would abort the pull; report them instead of raising."""
    report_rebuild(tool, summary)
    print("Status: LOCAL CHANGES NEED MERGING (not pulled over)")


def get_release(tool: cfg.ToolSpec) -> tuple[Release, Asset]:
    if tool.repo is None or tool.asset_pattern is None:
        raise UpdateError(f"Tool {tool.name} is missing release configuration")

    if tool.release_type == cfg.ReleaseType.PRERELEASE:
        releases = [
            release
            for release in cast(list[Release], github.get_json(f"{github.API}/repos/{tool.repo}/releases"))
            if release.get("prerelease")
        ]
        if not releases:
            raise UpdateError("No prerelease found")
        release = releases[0]
    else:
        release = cast(Release, github.get_json(f"{github.API}/repos/{tool.repo}/releases/latest"))

    asset = next((asset for asset in release["assets"] if re.search(tool.asset_pattern, asset["name"])), None)
    if not asset:
        raise UpdateError(f"Asset not found. Pattern: {tool.asset_pattern}")
    return release, asset


def get_local_version(tool: cfg.ToolSpec, exe: Path) -> str | None:
    if not exe.exists():
        print("Local: NOT FOUND")
        return None

    env = os.environ.copy()
    env["TEMP"] = env["TMP"] = str(project_cfg.component("shared").cache_dir / "framework_updates")
    result = subprocess.run(
        [str(exe), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30
    )
    text = result.stdout + result.stderr

    print(text.strip())
    if tool.version_regex:
        m = re.search(tool.version_regex, text)
        if m:
            return f"{tool.version_prefix}{m.group(1)}"
    return None


def download_asset(asset: Asset, tmp_dir: Path) -> Path:
    dest_file = tmp_dir / asset["name"]
    resp = requests.get(asset["browser_download_url"], stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest_file, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    digest = asset.get("digest")
    if digest and digest.startswith("sha256:"):
        with dest_file.open("rb") as downloaded:
            actual_digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual_digest != digest.removeprefix("sha256:"):
            raise UpdateError(f"Downloaded asset checksum mismatch: {asset['name']}")
    return dest_file


def staging_directory(parent: Path, prefix: str = "") -> Path:
    """Create a scratch directory that inherits `parent`'s permissions.

    `tempfile.mkdtemp` uses mode 0700, and on Windows that DACL denies the
    restricted token a sandboxed run holds, so nested writes and cleanup fail.
    """
    folder = Path(parent) / f"{prefix}{time.time_ns()}"
    folder.mkdir(parents=True)
    return folder


@contextlib.contextmanager
def staging_scope(parent: Path, prefix: str = "") -> Iterator[Path]:
    folder = staging_directory(parent, prefix)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def update_tool(asset: Asset, dest_dir: Path, tmp_dir: Path, exe_name: str) -> None:
    dest_dir = dest_dir.resolve()
    dest_dir.relative_to(project_cfg.FRAMEWORKS_DIR.resolve())
    dest_file = download_asset(asset, tmp_dir)
    staged = staging_directory(tmp_dir, prefix=dest_dir.name + "-")
    if any(dest_file.name.endswith(suffix) for suffix in (".zip", ".tar.gz", ".tar.bz2", ".tar.xz", ".tar")):
        shutil.unpack_archive(str(dest_file), str(staged))
    else:
        # Keep versioned standalone executables/installers at their catalog filename.
        shutil.copy(dest_file, staged / exe_name)
    if not (staged / exe_name).is_file():
        matches = list(staged.rglob(exe_name))
        if len(matches) == 1:
            staged = matches[0]
            for _ in Path(exe_name).parts:
                staged = staged.parent
    if not (staged / exe_name).is_file():
        raise UpdateError(f"Downloaded release is missing {exe_name}")
    replace_installation(staged, dest_dir)


def replace_installation(staged: Path, dest_dir: Path) -> None:
    dest_dir = dest_dir.resolve()
    dest_dir.relative_to(project_cfg.FRAMEWORKS_DIR.resolve())
    stop_installation_processes(dest_dir)
    if dest_dir.exists():
        archive_path(dest_dir, project_cfg.FRAMEWORKS_DIR)
    # - new files inherit installation permissions instead of cache integrity labels
    shutil.copytree(staged, dest_dir)


def _runs_from(value: str, target: str) -> bool:
    """True when one command-line value names the installation, as a path or as --x=VALUE."""
    target_prefix = target.rstrip("\\")
    raw = os.path.normcase(str(value).strip('"').replace("/", "\\"))
    occurrence = raw.find(target_prefix)
    if occurrence >= 0:
        suffix = raw[occurrence + len(target_prefix) :]
        if not suffix or suffix.startswith(("\\", "=")):
            return True
    try:
        candidate = os.path.normcase(os.path.abspath(str(value).strip('"')))
        return os.path.commonpath((target, candidate)) == target
    except ValueError:
        return False


def _matching_processes(target: str) -> list[psutil.Process]:
    import psutil

    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        info = process.info
        values = [info.get("exe"), *(str(argument) for argument in (info.get("cmdline") or []))]
        if any(_runs_from(value, target) for value in values if value):
            matches.append(process)
    return matches


def _process_tree(matches: list[psutil.Process]) -> dict[int, psutil.Process]:
    import psutil

    tree: dict[int, psutil.Process] = {}
    for process in matches:
        try:
            for child in process.children(recursive=True):
                tree[child.pid] = child
            tree[process.pid] = process
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise UpdateError(f"Cannot inspect child processes of PID {process.pid}: {error}") from error
    return tree


def _terminate_processes(processes: list[psutil.Process], dest_dir: Path) -> None:
    import psutil

    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise UpdateError(f"Cannot stop process PID {process.pid}; update was not started: {error}") from error
    _, alive = psutil.wait_procs(processes, timeout=10)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise UpdateError(f"Cannot kill process PID {process.pid}; update was not started: {error}") from error
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        remaining = ", ".join(f"PID {process.pid}" for process in alive)
        raise UpdateError(f"Services are still running from {dest_dir}: {remaining}; update was not started")


def stop_installation_processes(dest_dir: Path) -> list[int]:
    """Stop processes running from or launched with paths inside an installation."""
    target = os.path.normcase(os.path.abspath(dest_dir))
    matches = _matching_processes(target)
    if not matches:
        return []
    # Stop child processes as well, so a launcher cannot leave a backend alive.
    tree = _process_tree(matches)
    _terminate_processes(list(tree.values()), dest_dir)
    stopped = sorted(tree)
    print(f"Stopped {len(stopped)} process(es) for {dest_dir}: {', '.join(map(str, stopped))}")
    return stopped


def stop_update_services(
    tools: list[cfg.ToolSpec], summary: UpdateSummary, log: TextIO | None = None, extra_names: tuple[str, ...] = ()
) -> bool:
    """Quiesce only installations whose check found an update to apply."""
    selected = selected_for_apply(tools, summary)
    destinations = {(project_cfg.framework_install_dir(tool.name) / tool.install_subdir).resolve() for tool in selected}
    destinations.update(project_cfg.framework_install_dir(name).resolve() for name in extra_names)
    failed = False
    for destination in destinations:
        try:
            stop_installation_processes(destination)
        except (UpdateError, OSError) as error:
            failed = True
            print(f"[FAIL] Could not stop services for {destination}: {error}")
            if log is not None:
                log.write(f"Service shutdown failed for {destination}: {error}\n")
                log.flush()
    return failed


def download_source_folder(repo: str, commit: str, source_path: str, destination: Path) -> None:
    entries = github.get_json(f"{github.API}/repos/{repo}/contents/{source_path}", params={"ref": commit})
    destination.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry["type"] == "dir":
            download_source_folder(repo, commit, entry["path"], destination / entry["name"])
        elif entry["type"] == "file":
            content = requests.get(entry["download_url"], timeout=60)
            content.raise_for_status()
            (destination / entry["name"]).write_bytes(content.content)


def process_snapshot(tool: cfg.ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool) -> bool:
    commit = github.get_json(f"{github.API}/repos/{tool.repo}/commits/{tool.branch}")["sha"]
    marker = dest_dir / "SOURCE.json"
    local = json.loads(marker.read_text(encoding="utf-8"))["commit"] if marker.exists() else None
    print(f"Local commit: {local or 'NOT INSTALLED'}\nUpstream commit: {commit}")
    if local == commit:
        print("Status: UP TO DATE")
        return False
    print("Status: UPDATE AVAILABLE")
    if check_only:
        return True
    staged = tmp_dir / dest_dir.name
    staged.mkdir()
    if not tool.source_path:
        response = requests.get(f"https://github.com/{tool.repo}/archive/{commit}.zip", timeout=60)
        response.raise_for_status()
        archive = tmp_dir / (dest_dir.name + ".zip")
        archive.write_bytes(response.content)
        shutil.unpack_archive(str(archive), str(staged))
        staged = next(staged.iterdir())
    elif Path(tool.source_path).suffix:
        response = requests.get(
            f"https://raw.githubusercontent.com/{tool.repo}/{commit}/{tool.source_path}", timeout=60
        )
        response.raise_for_status()
        (staged / Path(tool.source_path).name).write_bytes(response.content)
    else:
        download_source_folder(str(tool.repo), commit, tool.source_path, staged)
    modifier = SNAPSHOT_MODIFIERS.get(tool.name)
    changes = modifier(staged) if modifier else []
    metadata = {
        "repository": f"https://github.com/{tool.repo}",
        "commit": commit,
        "upstream_path": tool.source_path,
        "local_changes": changes,
    }
    (staged / "SOURCE.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    replace_installation(staged, dest_dir)
    print("Status: UPDATED")
    return True


def snapshot_source_patches(tool: cfg.ToolSpec, dest_dir: Path, local: str, latest: str, status: str) -> Path:
    if SOURCE_PATCH_WRITER is None:
        raise UpdateError("No source patch writer is registered")
    return SOURCE_PATCH_WRITER(tool, dest_dir, local, latest, status)


def source_ahead(command: list[str], branch: str) -> bool:
    """Local commits on top of upstream make a --ff-only pull impossible."""
    result = subprocess.run(
        [*command, "rev-list", "--count", f"origin/{branch}..HEAD"], capture_output=True, text=True, check=False
    )
    count = result.stdout.strip()
    return result.returncode == 0 and count.isdigit() and int(count) > 0


def source_tree_dirty(command: list[str]) -> bool:
    """Tracked local edits block a fast-forward; untracked build output does not."""
    status = subprocess.run(
        [*command, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, check=False
    )
    return bool(status.stdout.strip())


def _head_commit(dest_dir: Path) -> str:
    return subprocess.check_output(["git", "-C", str(dest_dir), "rev-parse", "HEAD"], text=True).strip()


def _clone_source(tool: cfg.ToolSpec, dest_dir: Path) -> str:
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", tool.branch, f"https://github.com/{tool.repo}.git", str(dest_dir)],
        check=True,
    )
    print("Status: SOURCE INSTALLED (not compiled)")
    return _head_commit(dest_dir)


def _install_missing_source(
    tool: cfg.ToolSpec, dest_dir: Path, summary: UpdateSummary | None, check_only: bool, latest: str
) -> str:
    if summary is not None:
        summary.record(tool, "available", "not installed")
    print(f"Local commit  : NOT INSTALLED\nUpstream commit: {latest}")
    return latest if check_only else _clone_source(tool, dest_dir)


def _checkout_ahead(tool: cfg.ToolSpec, command: list[str], dest_dir: Path) -> bool:
    """Local commits on top of upstream make a --ff-only pull impossible."""
    if SOURCE_AHEAD_CHECK and SOURCE_AHEAD_CHECK(tool, dest_dir):
        return True
    return source_ahead(command, tool.branch)


def _pull(command: list[str], branch: str, options: tuple[str, ...] = ()) -> None:
    subprocess.run([*command, "pull", *options, "origin", branch], check=True)


def _replay_local_commit(
    tool: cfg.ToolSpec, command: list[str], summary: UpdateSummary | None, check_only: bool
) -> None:
    # - Our own patch commit is replayed on top of upstream, so it stays one known change.
    print("Status: UPDATE AVAILABLE; LOCAL COMMIT REPLAYED ON PULL")
    if summary is not None:
        summary.record(tool, "source_build" if tool.rebuild_required else "available", actionable=True)
    if not check_only:
        _pull(command, tool.branch, ("--rebase", "--autostash"))
        print("Status: SOURCE UPDATED; REBUILD REQUIRED")


def _fast_forward(tool: cfg.ToolSpec, command: list[str], summary: UpdateSummary | None, check_only: bool) -> None:
    if tool.rebuild_required:
        # - clean checkout: fast-forward is safe, but the binary stays stale until
        #   someone recompiles, so this is not reported as a finished update.
        report_source_build(tool, summary)
        if not check_only:
            _pull(command, tool.branch, ("--ff-only",))
            print("Status: SOURCE UPDATED; BUILD REQUIRED")
        return
    if summary is not None:
        summary.record(tool, "available")
    print("Status: UPDATE AVAILABLE")
    if not check_only:
        _pull(command, tool.branch, ("--ff-only",))
        print("Status: UPDATED")


def _apply_behind(
    tool: cfg.ToolSpec, command: list[str], dest_dir: Path, summary: UpdateSummary | None, check_only: bool, ahead: bool
) -> None:
    """Report, and where it is safe, move a checkout that is behind upstream."""
    if tool.rebase_local:
        if source_tree_dirty(command):
            report_local_changes(tool, summary)
        else:
            _replay_local_commit(tool, command, summary, check_only)
        return
    if tool.manual_merge or ahead:
        report_rebuild(tool, summary)
        return
    if source_tree_dirty(command):
        report_local_changes(tool, summary)
        return
    _fast_forward(tool, command, summary, check_only)


def process_source(tool: cfg.ToolSpec, dest_dir: Path, check_only: bool, summary: UpdateSummary | None = None) -> str:
    url = f"{github.API}/repos/{tool.repo}/commits/{tool.branch}"
    try:
        latest = github.get_json(url)["sha"]
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            raise UpdateError(
                f"Upstream unavailable: {tool.repo}, branch {tool.branch} (HTTP 404). "
                "Check whether the repository/branch moved or requires access; local installation is preserved."
            ) from error
        raise
    if not dest_dir.exists():
        return _install_missing_source(tool, dest_dir, summary, check_only, latest)
    command = ["git", "-c", f"safe.directory={dest_dir.as_posix()}", "-C", str(dest_dir)]
    local = subprocess.run([*command, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    print(f"Local commit  : {local.stdout.strip()}\nUpstream commit: {latest}")
    if SOURCE_DIRTY_CHECK and SOURCE_DIRTY_CHECK(tool, dest_dir, local.stdout.strip(), latest, check_only, summary):
        return local.stdout.strip()
    contains = subprocess.run([*command, "merge-base", "--is-ancestor", latest, "HEAD"], capture_output=True)
    if contains.returncode == 0:
        if summary is not None:
            summary.record(tool, "current")
        print("Status: SOURCE UP TO DATE")
    elif contains.returncode in (1, 128):
        _apply_behind(tool, command, dest_dir, summary, check_only, _checkout_ahead(tool, command, dest_dir))
    else:
        raise UpdateError(contains.stderr.decode("utf-8", errors="replace"))
    return _head_commit(dest_dir)


def installed_release_asset(tool: cfg.ToolSpec, dest_dir: Path) -> str | None:
    marker = dest_dir / ASSET_MARKER_NAME
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip()
    fallback = ASSET_FALLBACKS.get(tool.name)
    return fallback(dest_dir) if fallback else None


def process_managed_tool(
    tool: cfg.ToolSpec, dest_dir: Path, tmp_dir: Path, check_only: bool, summary: UpdateSummary | None
) -> bool:
    if handler := MANAGED_HANDLERS.get(tool.release_type):
        handler(tool, dest_dir, tmp_dir, check_only, summary)
        return True
    if tool.release_type == cfg.ReleaseType.SOURCE:
        process_source(tool, dest_dir, check_only, summary=summary)
        return True
    if tool.release_type == cfg.ReleaseType.SNAPSHOT:
        needed = process_snapshot(tool, dest_dir, tmp_dir, check_only)
        if summary is not None:
            summary.record(tool, "available" if needed else "current")
        return True
    if tool.release_type == cfg.ReleaseType.MANUAL:
        if summary is not None:
            summary.record(tool, "manual_check")
        print("Status: MANUAL UPDATE REQUIRED (support tooling)")
        return True
    return False


def _needs_update(tool: cfg.ToolSpec, release: Release, asset: Asset, dest_dir: Path, exe: Path) -> bool:
    remote_stamp = release["published_at"]
    if tool.release_type in (cfg.ReleaseType.DATE, cfg.ReleaseType.WHEEL):
        # Compare against the release timestamp recorded at install time,
        # not the exe's mtime (zip extraction can preserve old file dates).
        marker = dest_dir / MARKER_NAME
        local_stamp = marker.read_text().strip() if marker.exists() else None
        local_asset = installed_release_asset(tool, dest_dir)
        print(f"Local release : {local_stamp or 'UNKNOWN'}")
        print(f"Latest release: {remote_stamp}")
        if local_asset:
            print(f"Local asset   : {local_asset}")
        return (
            not exe.exists()
            or local_stamp != remote_stamp
            or (local_asset is not None and local_asset != asset["name"])
        )
    local_version = get_local_version(tool, exe)
    latest_version = release["tag_name"]
    print(f"Local version : {local_version}")
    print(f"Latest version: {latest_version}")
    return not local_version or local_version != latest_version


def _install_release(tool: cfg.ToolSpec, asset: Asset, dest_dir: Path, tmp_dir: Path, release: Release) -> None:
    print("Status: UPDATING")
    installer = RELEASE_INSTALLERS.get(tool.release_type, update_tool)
    installer(asset, dest_dir, tmp_dir, tool.exe)
    if tool.release_type in (cfg.ReleaseType.DATE, cfg.ReleaseType.WHEEL):
        (dest_dir / MARKER_NAME).write_text(release["published_at"])
        (dest_dir / ASSET_MARKER_NAME).write_text(asset["name"], encoding="utf-8")
    print("Status: UPDATED")


def process_tool(tool: cfg.ToolSpec, tmp_dir: Path, check_only: bool, summary: UpdateSummary | None = None) -> bool:
    dest_dir = project_cfg.framework_install_dir(tool.name) / tool.install_subdir
    exe = dest_dir / tool.exe
    label = tool_label(tool)
    print(f"\n=== {label} ===")

    try:
        if not tool.in_use:
            print("Status: NOT CURRENTLY IN USE (skipped)")
            return True
        if process_managed_tool(tool, dest_dir, tmp_dir, check_only, summary):
            return True

        release, asset = get_release(tool)
        print(f"Latest: {release['tag_name']}")
        print(f"Asset : {asset['name']}")
        if note := RELEASE_NOTES.get(tool.name):
            note(release)

        needs_update = _needs_update(tool, release, asset, dest_dir, exe)
        if summary is not None:
            summary.record(tool, "available" if needs_update else "current")
        if not needs_update:
            print("Status: UP TO DATE")
            return True
        print("Status: UPDATE AVAILABLE")
        if not check_only:
            _install_release(tool, asset, dest_dir, tmp_dir, release)
        return True

    except UpdateError as error:
        print(f"Status: FAILED; {error}")
        return False
    except subprocess.SubprocessError as error:
        # - expected per-tool failures may continue; keep the captured reason visible
        print(f"Status: FAILED; {error}")
        return False
    except (requests.RequestException, OSError):
        import traceback

        traceback.print_exc()
        return False


def check_tools(tools: list[cfg.ToolSpec], folder: Path, summary: UpdateSummary, log: TextIO) -> None:
    for index, tool in enumerate(tools, 1):
        print(f"\rChecking frameworks: {index}/{len(tools)}", end="", flush=True)
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                success = process_tool(tool, folder, True, summary=summary)
        finally:
            log.write(captured.getvalue())
            log.flush()
        if not success:
            summary.discard(tool)
            summary.record(tool, "failures")
    if tools:
        print()


def save_pending_patches(summary: UpdateSummary, log: TextIO) -> bool:
    failed = []
    if summary.patch_sources:
        print("\n=== LOCAL PATCH BACKUPS ===")
    for tool, directory, latest in summary.patch_sources:
        command = ["git", "-c", f"safe.directory={directory.as_posix()}", "-C", str(directory)]
        try:
            local = subprocess.run(
                [*command, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            dirty = subprocess.run(
                [*command, "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout
            if dirty.strip():
                path = snapshot_source_patches(tool, directory, local, latest, dirty)
                print(f"- {tool.name}: {path}")
        except (OSError, subprocess.SubprocessError) as error:
            failed.append(tool.name)
            log.write(f"Patch backup failed: {tool.name}: {error}\n")
    if failed:
        print("\n=== PATCH BACKUP FAILED ===")
        for name in failed:
            print(f"- {name}")
    return bool(failed)


def selected_for_apply(tools: list[cfg.ToolSpec], summary: UpdateSummary) -> list[cfg.ToolSpec]:
    """Tools with a found update, plus post-install steps that still have work to do."""
    return [
        tool
        for tool in tools
        if tool_label(tool) in summary.apply_keys
        or (tool.name in POST_INSTALLERS and POST_INSTALL_PENDING.get(tool.name, lambda _tool: False)(tool))
    ]


def apply_updates(tools: list[cfg.ToolSpec], folder: Path, summary: UpdateSummary, log: TextIO) -> bool:
    selected = selected_for_apply(tools, summary)
    if not selected:
        return False
    if stop_update_services(selected, summary, log):
        print("[FAIL] Updates were not started because one or more services could not be stopped.")
        return True
    print("\n=== APPLYING UPDATES ===")
    updated, failed = [], []
    for index, tool in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] Updating {tool_label(tool)}", flush=True)
        success = apply_one_update(tool, folder, log)
        (updated if success else failed).append(tool_label(tool))
    for title, names in (("UPDATE COMMAND COMPLETED", updated), ("UPDATE FAILED", failed)):
        if names:
            print(f"\n=== {title} ===")
            for name in names:
                print(f"- {name}")
    builds = [tool_label(tool) for tool in selected if tool.rebuild_required and tool_label(tool) in updated]
    if builds:
        print("\n=== BUILD REQUIRED ===")
        for name in builds:
            print(f"- {name}: source updated; recompile before it is used again")
        print("\nRun: C:/AI/bat/build_frameworks.bat")
    return bool(failed)


def apply_one_update(tool: cfg.ToolSpec, folder: Path, log: TextIO) -> bool:
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            success = process_tool(tool, folder, False)
            if success:
                success = run_post_install(tool)
    finally:
        log.write(captured.getvalue())
        log.flush()
    return success


def run_post_install(tool: cfg.ToolSpec) -> bool:
    post_install = POST_INSTALLERS.get(tool.name)
    if post_install is None:
        return True
    try:
        post_install(tool)
    except (UpdateError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"Status: POST-INSTALL FAILED; {error}")
        return False
    return True
