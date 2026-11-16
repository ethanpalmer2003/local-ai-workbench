"""Update framework categories; check every selected tool before applying changes."""

import argparse
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import build_frameworks, toolchains
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks.coding_agents.pi import packages as pi_packages
from scripts.shared import consent

# - a check plus the installs it decides on is minutes of network and unpacking
UPDATE_SECONDS = 600


def missing_builds(tools: list[cfg.ToolSpec]) -> list[cfg.ToolSpec]:
    """Source builds the update just touched that have no install directory yet."""
    return [
        tool
        for tool in build_frameworks.build_targets([tool.name for tool in tools])
        if not project_cfg.framework_install_dir(tool.name).is_dir()
    ]


def offer_missing_builds(tools: list[cfg.ToolSpec], *, check_only: bool, assume_yes: bool) -> bool:
    """An absent install is not an update: offer it once, after the plan is shown. True when a build failed."""
    missing = missing_builds(tools)
    if check_only or not missing:
        return False
    return bool(build_missing(missing, assume_yes=assume_yes))


def build_missing(missing: list[cfg.ToolSpec], *, assume_yes: bool) -> int:
    """Ask once whether to build absent installs, then build them here; returns failures."""
    names = ", ".join(tool.name for tool in missing)
    if not assume_yes:
        answer = input(f"\n[BUILD] {len(missing)} source install(s) missing: {names}. Build now? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print(f"[SKIP] Build later with: C:/AI/bat/update_frameworks.bat --only {missing[0].name}")
            return 0
    return build_frameworks.run_builds(missing, foreground=True)


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
    cache = project_cfg.component("shared").cache_dir / "framework_updates"
    cache.mkdir(parents=True, exist_ok=True)
    log_path = project_cfg.component("shared").logs_dir / "framework_updates" / f"{time.time_ns()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        updater.staging_scope(cache, prefix="framework-updates-") as folder,
        log_path.open("w", encoding="utf-8") as log,
    ):
        updater.check_tools(tools, Path(folder), summary, log)
        summary.print()
        failed = offer_missing_builds(tools, check_only=args.check_only, assume_yes=args.build_missing) or bool(
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
                print(
                    "\n=== UPDATE BLOCKED ===\n- At least one related service could not be stopped; no updates were started."
                )
                failed = True
            else:
                failed = updater.save_pending_patches(summary, log) or failed
                if pi_needs_sync:
                    print("\n=== PI PACKAGE SYNC ===")
                    pi_packages.sync(apply=True)
                failed = updater.apply_updates(tools, Path(folder), summary, log) or failed
                failed = toolchains.apply(toolchain_rows) or failed
    print(f"\nDetails: {log_path}")
    print("\n=== COMPLETE ===")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
