"""Update framework categories; check every selected tool before applying changes."""

import argparse
import time
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as cfg
from scripts.download.frameworks import update_shared as updater
from scripts.download.frameworks.coding_agents.pi import packages as pi_packages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-comfyui", action="store_true")
    parser.add_argument(
        "--check-only", action="store_true", help="check everything and print groups without installing"
    )
    parser.add_argument("--only", help="select a catalog name or group prefix, for example llamacpp/additions/hrx")
    parser.add_argument("--category", choices=tuple(cfg.CATEGORIES), help="select llama.cpp, TTS/ASR, or other tools")
    args = parser.parse_args()
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
        failed = bool(summary.failures)
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
    print(f"\nDetails: {log_path}")
    print("\n=== COMPLETE ===")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
