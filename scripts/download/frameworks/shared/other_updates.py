"""Other framework catalog and delegated/package update handlers."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import requests
import yaml

from scripts.config import project_config as project_cfg
from scripts.config.coding_agents.pi import packages as pi_packages
from scripts.download.frameworks import update_shared as shared
from scripts.download.frameworks import update_types as cfg
from scripts.download.frameworks.npm import command as npm_command
from scripts.download.frameworks.update_types import ReleaseType, ToolSpec


def pi_tools() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(pi_packages.INSTALL_NAME, "", ReleaseType.NPM, package=pi_packages.manifest()["core_package"]),
        *(
            ToolSpec(pi_packages.INSTALL_NAME, "", ReleaseType.NPM, package=item.package, in_use=item.enabled)
            for item in pi_packages.extensions(include_disabled=True)
        ),
    )


def benchmark_tools() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            "benchmarks/aider-polyglot", "", ReleaseType.SOURCE, repo="Aider-AI/polyglot-benchmark", group="benchmarks"
        ),
        ToolSpec("benchmarks/club-rdna16", "", ReleaseType.SNAPSHOT, repo="5p00kyy/club-rdna16", group="benchmarks"),
        ToolSpec(
            "benchmarks/specspeed",
            "specspeed.py",
            ReleaseType.SNAPSHOT,
            repo="aipruner/qwen3.8-3bit-test-in-16GB-GPU",
            source_path="harness/specspeed.py",
            group="benchmarks",
        ),
        ToolSpec(
            "benchmarks/speed-bench",
            "speed_bench.py",
            ReleaseType.SNAPSHOT,
            repo="ggml-org/llama.cpp",
            branch="master",
            source_path="tools/server/bench/speed-bench",
            group="benchmarks",
        ),
    )


TOOLS = [
    ToolSpec("strata", "", ReleaseType.STRATA),
    # - Avalon is an unmodified llama.cpp fork cloned and compiled by hand with cmake.
    #   The catalog records the upstream so the install is covered; a newer commit is
    #   fast-forwarded, then reported as still needing a build, never as merged patches.
    #   Deferred: the fork trails stable llama.cpp and lost the paired screen, so it is
    #   not checked until it earns another look.
    ToolSpec(
        "avalon",
        "build/bin/llama-server.exe",
        ReleaseType.SOURCE,
        repo="freriadoc/Avalon",
        rebuild_required=True,
        rebase_local=True,
        in_use=False,
        build_command=("cmake", "--build", "build", "--target", "llama-server"),
    ),
    *benchmark_tools(),
    *pi_tools(),
    ToolSpec("coding_agents/commandcode", "", ReleaseType.NPM, package="command-code"),
    ToolSpec(
        "coding_agents/commandcode-desktop",
        "Command Code.exe",
        ReleaseType.DESKTOP,
        repo="CommandCodeAI/gui",
        asset_pattern=r"^CommandCode-.*-x64-setup\.exe$",
        group="coding_agents/commandcode",
    ),
    # - Benchmark and launcher clients stay tracked: they are exercised on this host,
    #   so a stale install shows up as a failed task rather than an update notice.
    ToolSpec("coding_agents/littlecoder", "", ReleaseType.NPM, package="little-coder"),
    ToolSpec("coding_agents/nanocoder", "", ReleaseType.NPM, package="@nanocollective/nanocoder"),
    ToolSpec(
        "coding_agents/ohmypi",
        "omp-windows-x64.exe",
        ReleaseType.RELEASE,
        repo="can1357/oh-my-pi",
        asset_pattern=r"^omp-windows-x64\.exe$",
        version_regex=r"(\d+\.\d+\.\d+)",
        version_prefix="v",
    ),
    ToolSpec(
        "coding_agents/deepseek",
        "DeepSeek Harness.exe",
        ReleaseType.DESKTOP,
        feed="https://download.deepseek.com/dsh-desk/feeds/win-x64",
        channel="nightly",
    ),
    ToolSpec("lemonade_server", "", ReleaseType.MANUAL, in_use=False),
    # - Model servers stay parked until one is installed and exercised: each ships its own
    #   launcher, so a version check would only restate the vendor's updater. LocalAI 4.12.1
    #   publishes no Windows binary (linux, darwin, AppImage, dmg and source only); Text
    #   generation WebUI publishes portable zips (cpu, vulkan, rocm, cuda) but is not installed.
    ToolSpec("localai", "", ReleaseType.MANUAL, repo="mudler/LocalAI", in_use=False),
    ToolSpec("text-generation-webui", "", ReleaseType.MANUAL, repo="oobabooga/text-generation-webui", in_use=False),
    ToolSpec(
        name=project_cfg.SDCPP_ROCM_DIR.relative_to(project_cfg.FRAMEWORKS_DIR).as_posix(),
        repo="leejet/stable-diffusion.cpp",
        exe="sd-cli.exe",
        asset_pattern=r"sd-master-.*-bin-win-rocm-\d+\.\d+(?:\.\d+)?-x64\.zip",
        release_type=ReleaseType.DATE,
    ),
    ToolSpec(
        name=project_cfg.SDCPP_VULKAN_DIR.relative_to(project_cfg.FRAMEWORKS_DIR).as_posix(),
        repo="leejet/stable-diffusion.cpp",
        exe="sd-cli.exe",
        asset_pattern=r"^sd-master-.*-bin-win-vulkan-x64\.zip$",
        release_type=ReleaseType.DATE,
    ),
    ToolSpec(
        name="koboldcpp",
        repo="LostRuins/koboldcpp",
        exe="koboldcpp-nocuda.exe",
        asset_pattern=r"koboldcpp-nocuda\.exe",
        release_type=ReleaseType.RELEASE,
        version_regex=r"(\d+\.\d+(?:\.\d+)*)",
        version_prefix="v",
    ),
    ToolSpec(
        name=project_cfg.COMFYUI_ROCM_DIR.relative_to(project_cfg.FRAMEWORKS_DIR).as_posix(),
        exe="comfyui-rocm-updater.bat",
        release_type=ReleaseType.BAT,
        repo="patientx-cfz/comfyui-rocm",
        branch="master",
        tracked_checkouts="custom_nodes",
    ),
]


def process_npm(tool: cfg.ToolSpec, dest_dir: Path, check_only: bool) -> bool:
    if tool.package is None:
        raise shared.UpdateError(f"Missing npm package for {tool.name}")
    response = requests.get(f"https://registry.npmjs.org/{tool.package}/latest", timeout=30)
    response.raise_for_status()
    latest = response.json()["version"]
    manifest = dest_dir / "node_modules" / tool.package / "package.json"
    local = json.loads(manifest.read_text(encoding="utf-8"))["version"] if manifest.exists() else None
    print(f"Local version : {local or 'NOT INSTALLED'}\nLatest version: {latest}")
    if local == latest:
        print("Status: UP TO DATE")
        return False
    print("Status: UPDATE AVAILABLE")
    if not check_only:
        print(f"Status: UPDATING {tool.package} ({local or 'NOT INSTALLED'} -> {latest})")
        subprocess.run(
            [*npm_command(), "install", "--prefix", str(dest_dir), "--save-exact", f"{tool.package}@{latest}"],
            check=True,
        )
        print(f"Status: UPDATED {tool.package} -> {latest}")
    return True


GITHUB_REMOTE = re.compile(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", re.MULTILINE)
UPDATER_NODE = re.compile(r'call\s+:UpdateCustomNode\s+"([^"]+)"\s+"(https://github\.com/[^"]+)"', re.IGNORECASE)


def managed_nodes(script: Path) -> list[tuple[str, str]]:
    """Custom nodes the vendor updater itself pulls, read from its own script."""
    if not script.is_file():
        return []
    return UPDATER_NODE.findall(script.read_text(encoding="utf-8", errors="replace"))


def checkout_drift(folder: Path, managed: set[str]) -> list[tuple[str, str, str, bool]]:
    """Checkouts whose HEAD is behind their GitHub origin; the flag marks vendor-managed ones."""
    drift: list[tuple[str, str, str, bool]] = []
    if not folder.is_dir():
        return drift
    for checkout in sorted(folder.iterdir()):
        config = checkout / ".git" / "config"
        if not config.is_file():
            continue
        remote = GITHUB_REMOTE.search(config.read_text(encoding="utf-8", errors="replace"))
        if remote is None:
            continue
        command = ["git", "-c", f"safe.directory={checkout.as_posix()}", "-C", str(checkout)]
        branch = subprocess.run(
            [*command, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        local = subprocess.run([*command, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        if not branch or not local.stdout.strip():
            continue
        latest = shared.github.get_json(
            f"{shared.github.API}/repos/{remote.group(1)}/{remote.group(2)}/commits/{branch}"
        )
        if local.stdout.strip() != latest["sha"]:
            drift.append((checkout.name, local.stdout.strip()[:7], latest["sha"][:7], checkout.name in managed))
    return drift


def pull_checkout(checkout: Path) -> str:
    """Fast-forward a single checkout; raises when upstream and local have diverged."""
    command = ["git", "-c", f"safe.directory={checkout.as_posix()}", "-C", str(checkout)]
    branch = subprocess.run(
        [*command, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    subprocess.run([*command, "pull", "--ff-only", "origin", branch], check=True, timeout=180)
    return subprocess.run(
        [*command, "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()


def _report_drift(drift: list[tuple[str, str, str, bool]]) -> None:
    for name, local_sha, remote_sha, via_vendor in drift:
        print(f"  behind: {name} {local_sha} -> {remote_sha} ({'vendor updater' if via_vendor else 'updater pull'})")


def _pull_drift(folder: Path, drift: list[tuple[str, str, str, bool]]) -> None:
    for name, _local_sha, _remote_sha, via_vendor in drift:
        if not via_vendor:
            print(f"Status: PULLING {name}")
            pull_checkout(folder / name)


def _launch_updater(exe: Path, dest_dir: Path) -> None:
    print("Status: UPDATING IN NEW TERMINAL")
    env = os.environ.copy()
    env["PIP_REQUIRE_VIRTUALENV"] = "false"
    subprocess.Popen(["cmd.exe", "/k", str(exe)], cwd=dest_dir, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def _vendor_batch_state(
    tool: ToolSpec, dest_dir: Path, exe: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> bool:
    """None-safe report of a vendor-managed checkout: True when the call is finished."""
    if not tool.repo:
        print("Status: MANUAL CHECK REQUIRED")
        if summary is not None:
            summary.record(tool, "manual_check", "external updater; version check unavailable", actionable=True)
        return True
    command = ["git", "-c", f"safe.directory={dest_dir.as_posix()}", "-C", str(dest_dir)]
    local = subprocess.run([*command, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    latest = shared.github.get_json(f"{shared.github.API}/repos/{tool.repo}/commits/{tool.branch}")["sha"]
    print(f"Local commit  : {local.stdout.strip() or 'NOT INSTALLED'}\nUpstream commit: {latest}")
    folder = dest_dir / tool.tracked_checkouts
    drift = checkout_drift(folder, {name for name, _url in managed_nodes(exe)}) if tool.tracked_checkouts else []
    _report_drift(drift)
    core_stale = local.stdout.strip() != latest
    if not core_stale and not drift:
        print("Status: UP TO DATE")
        if summary is not None:
            summary.record(tool, "current")
        return True
    print("Status: UPDATE AVAILABLE")
    if summary is not None:
        summary.record(tool, "available", f"{len(drift)} custom node(s) behind" if drift else "")
    if check_only:
        return True
    _pull_drift(folder, drift)
    if not core_stale and not any(entry[3] for entry in drift):
        print("Status: UPDATED")
        return True
    return False


def process_bat(
    tool: ToolSpec, dest_dir: Path, exe: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> None:
    """Compare the checkout's commit when the entry names its repo, then run its updater."""
    if _vendor_batch_state(tool, dest_dir, exe, check_only, summary):
        return
    if not exe.exists():
        raise shared.UpdateError(f"Updater not found: {exe}")
    _launch_updater(exe, dest_dir)


def process_strata(tool: ToolSpec, dest_dir: Path, check_only: bool, summary: shared.UpdateSummary | None) -> None:
    from scripts.download.frameworks.strata import updates as strata_updates

    report = strata_updates.process(dest_dir, check_only)
    if summary is not None and report is not None:
        for part in ("engine", "control", "app"):
            status = report[part]["status"]
            group = (
                "available"
                if status in ("available", "install")
                else "current"
                if status == "current"
                else "manual_check"
            )
            summary.record(tool, group, strata_updates.describe(part, report[part]))


def installed_desktop_version(tool: ToolSpec, dest_dir: Path) -> str | None:
    manifest = dest_dir / "resources" / "app" / "package.json"
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))["version"]
    exe = dest_dir / tool.exe
    if not exe.is_file():
        return None
    # - Packaged builds keep package.json inside app.asar, so read the version the
    #   executable carries instead of launching the app.
    quoted = exe.as_posix().replace("'", "''")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{quoted}').VersionInfo.FileVersion"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def feed_details(tool: ToolSpec) -> tuple[str, str, str, int | None]:
    """Version, installer URL, sha512 (base64) and size from an electron-builder feed."""
    response = requests.get(f"{tool.feed.rstrip('/')}/{tool.channel}.yml", timeout=30)
    response.raise_for_status()
    data = yaml.safe_load(response.text) or {}
    files = data.get("files") or [{}]
    version = str(data.get("version") or "").strip()
    url = str(data.get("path") or files[0].get("url") or "").strip()
    digest = str(data.get("sha512") or files[0].get("sha512") or "").strip()
    size = files[0].get("size") or data.get("size")
    if not version or not url or not digest:
        raise shared.UpdateError(f"{tool.name}: incomplete update feed")
    return version, url, digest, int(size) if size else None


def app_running(dest_dir: Path) -> bool:
    """True while a process runs from inside the installation folder."""
    import psutil

    prefix = os.path.normcase(os.path.abspath(dest_dir)).rstrip("\\") + "\\"
    for process in psutil.process_iter(["exe"]):
        exe = process.info.get("exe")
        if exe and os.path.normcase(exe).startswith(prefix):
            return True
    return False


def stop_app(dest_dir: Path) -> None:
    """An installer owns its files: a running app is ended, not waited for."""
    import psutil

    prefix = os.path.normcase(os.path.abspath(dest_dir)).rstrip("\\") + "\\"
    for process in psutil.process_iter(["exe"]):
        exe = process.info.get("exe")
        if exe and os.path.normcase(exe).startswith(prefix):
            print(f"Status: STOPPING {process.pid}")
            try:
                process.kill()
                process.wait(timeout=15)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                continue


def download_feed_installer(tool: ToolSpec, details: tuple[str, str, str, int | None]) -> Path:
    _version, url, digest, size = details
    folder = project_cfg.component("shared").cache_dir / "desktop"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / url.rstrip("/").rsplit("/", 1)[-1]
    hasher = hashlib.sha512()
    written = 0
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with target.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1 << 20):
                output.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
    if size is not None and written != size:
        raise shared.UpdateError(f"{tool.name}: installer size {written} does not match the feed")
    if base64.b64encode(hasher.digest()).decode() != digest:
        raise shared.UpdateError(f"{tool.name}: installer sha512 does not match the feed")
    return target


def install_desktop(tool: ToolSpec, dest_dir: Path, version: str) -> None:
    """Install a newer desktop app silently, then confirm the version it reports."""
    if tool.feed:
        installer = download_feed_installer(tool, feed_details(tool))
    else:
        _release, asset = shared.get_release(tool)
        installer = shared.download_asset(asset, project_cfg.component("shared").cache_dir / "desktop")
    print(f"Status: INSTALLING {version}")
    subprocess.run([str(installer), "/S", f"/D={dest_dir}"], check=True, timeout=1800)
    installed = installed_desktop_version(tool, dest_dir)
    if installed != version:
        raise shared.UpdateError(f"{tool.name}: installer left {installed} installed, expected {version}")
    print(f"Status: UPDATED to {installed}")
    installer.unlink(missing_ok=True)


def process_desktop(tool: ToolSpec, dest_dir: Path, check_only: bool, summary: shared.UpdateSummary | None) -> None:
    """Compare the installed Electron app with its feed and install it when it is closed."""
    local = installed_desktop_version(tool, dest_dir)
    if tool.feed:
        latest = feed_details(tool)[0]
    else:
        release = shared.github.get_json(f"{shared.github.API}/repos/{tool.repo}/releases/latest")
        latest = str(release.get("tag_name", "")).lstrip("v")
    print(f"Local version : {local or 'NOT INSTALLED'}\nLatest version: {latest or 'UNKNOWN'}")
    if local and latest and local == latest:
        print("Status: UP TO DATE")
        if summary is not None:
            summary.record(tool, "current")
        return
    # - An update run owns the host: the app is stopped so the installer can replace it.
    if app_running(dest_dir):
        stop_app(dest_dir)
    print("Status: UPDATE AVAILABLE")
    if summary is not None:
        summary.record(tool, "available")
    if not check_only and latest:
        install_desktop(tool, dest_dir, latest)


def process_tool(
    tool: ToolSpec, destination: Path, temporary: Path, check_only: bool, summary: shared.UpdateSummary | None
) -> None:
    if tool.release_type == ReleaseType.NPM:
        needed = process_npm(tool, destination, check_only)
        if summary is not None:
            summary.record(tool, "available" if needed else "current")
    elif tool.release_type == ReleaseType.BAT:
        process_bat(tool, destination, destination / tool.exe, check_only, summary)
    elif tool.release_type == ReleaseType.STRATA:
        process_strata(tool, destination, check_only, summary)
    elif tool.release_type == ReleaseType.DESKTOP:
        process_desktop(tool, destination, check_only, summary)


def restrict_specspeed(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    node = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PROMPTS" for target in node.targets)
    )
    if not isinstance(node.value, ast.List):
        raise shared.UpdateError(f"specspeed PROMPTS is not a list literal: {path}")
    prompts = [entry for entry in node.value.elts if ast.literal_eval(entry)[0] in ("code", "code2", "prose_en")]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [
        "PROMPTS = " + ast.unparse(ast.List(elts=prompts, ctx=ast.Load())) + "\n"
    ]
    path.write_text("".join(lines), encoding="utf-8")


def modify_specspeed(directory: Path) -> list[str]:
    restrict_specspeed(directory / "specspeed.py")
    return ["Retained only code, code2, prose_en prompts; English/code only."]
