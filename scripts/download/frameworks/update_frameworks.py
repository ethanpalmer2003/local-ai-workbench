"""Update framework categories; check every selected tool before applying changes."""

import argparse
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import build_frameworks, toolchains
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks.coding_agents.pi import packages as pi_packages
from scripts.download.frameworks.llamacpp import rdna_build
from scripts.shared import consent

# - a check plus the installs it decides on is minutes of network and unpacking
UPDATE_SECONDS = 600
# - the RDNA build compiles llama.cpp, so it asks separately
RDNA_BUILD_SECONDS = 1500


def missing_builds(tools: list[cfg.ToolSpec]) -> list[cfg.ToolSpec]:
    """Source builds the update just touched that have no install directory yet."""
    return [
        tool
        for tool in build_frameworks.build_targets([tool.name for tool in tools])
        if not project_cfg.framework_install_dir(tool.name).is_dir()
    ]


def offer_missing_builds(tools: list[cfg.ToolSpec], *, check_only: bool, assume_yes: bool) -> bool:
    """Build the source installs still absent after the run; True when a build failed.

    The question is asked before the first check (see `main`), never after the plan: a run that stops
    halfway through its progress for an answer reads as a hung run.
    """
    missing = missing_builds(tools)
    if check_only or not missing or not assume_yes:
        return False
    return bool(build_missing(missing))


def build_missing(missing: list[cfg.ToolSpec]) -> int:
    """Build the absent installs here; returns failures."""
    return build_frameworks.run_builds(missing, foreground=True)


def run_requested_build(args: argparse.Namespace, allowed: bool) -> bool:
    """Run the parked build this run asked for; True when it failed or was not agreed."""
    if args.check_only or args.build != "rdna":
        return False
    if not allowed:
        return True
    print("\n=== RDNA BUILD ===")
    return build_rdna(assume_yes=True)


def consent_for_later_phases(tools: list[cfg.ToolSpec], args: argparse.Namespace) -> tuple[bool, bool]:
    """Every question this run can ask, before the first check: absent source builds, then a parked build.

    A prompt that arrives between progress lines reads as a hung run, so the answer is collected here
    and the later phases only act on it.
    """
    builds = False
    if not args.check_only:
        missing = missing_builds(tools)
        if missing:
            names = ", ".join(tool.name for tool in missing)
            builds = consent.ask(
                f"Framework build ({names})", build_frameworks.BUILD_SECONDS, args.build_missing or args.yes
            )
            if not builds:
                print(f"[SKIP] Build later with: C:/AI/bat/update_frameworks.bat --only {missing[0].name}")
    rdna = args.build == "rdna" and not args.check_only
    if rdna and not consent.ask("RDNA llama.cpp build", RDNA_BUILD_SECONDS, args.yes):
        return builds, False
    return builds, rdna


def build_rdna(assume_yes: bool) -> bool:
    """Run the parked RDNA-boosts build, which the update loop never starts on its own; True on failure."""
    if not consent.ask("RDNA llama.cpp build", RDNA_BUILD_SECONDS, assume_yes):
        return True
    parser = argparse.ArgumentParser(add_help=False)
    rdna_build.add_arguments(parser)
    namespace = parser.parse_args([])
    namespace.build_llamacpp_rdna = True
    try:
        rdna_build.run(namespace)
    except rdna_build.UpdateError as error:
        print(f"[FAIL] rdna build: {error}")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-comfyui", action="store_true")
    parser.add_argument(
        "--check-only", action="store_true", help="check everything and print groups without installing"
    )
    parser.add_argument("--only", help="select a catalog name or group prefix, for example llamacpp/additions/hrx")
    parser.add_argument("--category", choices=tuple(cfg.CATEGORIES), help="select llama.cpp, TTS/ASR, or other tools")
    parser.add_argument(
        "--build-missing",
        action="store_true",
        help="build every missing source install without asking; otherwise it asks once",
    )
    parser.add_argument(
        "--build",
        choices=("rdna",),
        help="run a parked build after updating: rdna compiles llama.cpp with the RDNA-boosts patch set",
    )
    consent.flag(parser)
    args = parser.parse_args()
    if not args.check_only and not consent.ask("Framework update", UPDATE_SECONDS, args.yes):
        return 1
    tools = [
        tool
        for tool in cfg.TOOLS
        if (not args.only or tool.name == args.only or tool.name.startswith(args.only + "/"))
        and (not args.category or tool.category == args.category)
    ]
    if not tools:
        parser.error(f"No catalog entries match {args.only!r}")
    # - Inactive entries are ignored outright: no check, no network call, no listing.
    tools = [tool for tool in tools if tool.in_use]
    if not tools:
        parser.error(f"No active catalog entries match {args.only!r}")
    summary = updater.UpdateSummary(
        categories={updater.tool_label(tool): tool.category for tool in tools},
        kinds={updater.tool_label(tool): cfg.update_kind(tool) for tool in tools},
    )
    if args.skip_comfyui:
        summary.skipped = [updater.tool_label(tool) for tool in tools if tool.name == "comfyui/rocm"]
        tools = [tool for tool in tools if tool.name != "comfyui/rocm"]
    pi_selected = any(tool.name == "coding_agents/pi" for tool in tools)
    if pi_selected:
        additions, removals = pi_packages.sync_plan()
        summary.package_sync = [f"Install {name}" for name in additions] + [f"Remove {name}" for name in removals]
    # - asked here, before the first check, so no phase stops the progress for an answer
    builds_allowed, rdna_allowed = consent_for_later_phases(tools, args)
    cache = project_cfg.component("shared").cache_dir / "framework_updates"
    cache.mkdir(parents=True, exist_ok=True)
    log_path = project_cfg.component("shared").logs_dir / "framework_updates" / f"{time.time_ns()}" / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        updater.staging_scope(cache, prefix="framework-updates-") as folder,
        # - line buffered: a window closed mid-update must not leave the plan lost in a buffer
        log_path.open("w", encoding="utf-8", buffering=1) as log,
    ):
        updater.check_tools(tools, Path(folder), summary, log)
        summary.print()
        failed = offer_missing_builds(tools, check_only=args.check_only, assume_yes=builds_allowed) or bool(
            summary.failures
        )
        toolchain_rows: list[toolchains.Row] = []
        if not args.only and not args.category:
            toolchain_rows = toolchains.check()
        if not args.check_only:
            pi_needs_sync = pi_selected and bool(summary.package_sync)
            if updater.stop_update_services(
                tools, summary, log, extra_names=("coding_agents/pi",) if pi_needs_sync else ()
            ):
                print("\n=== UPDATE BLOCKED ===")
                print("- At least one related service could not be stopped; no updates were started.")
                failed = True
            else:
                failed = updater.save_pending_patches(summary, log) or failed
                if pi_needs_sync:
                    print("\n=== PI PACKAGE SYNC ===")
                    pi_packages.sync(apply=True)
                failed = updater.apply_updates(tools, Path(folder), summary, log) or failed
                failed = toolchains.apply(toolchain_rows) or failed
    failed = run_requested_build(args, rdna_allowed) or failed
    print(f"\nDetails: {log_path}")
    print("\n=== COMPLETE ===")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
