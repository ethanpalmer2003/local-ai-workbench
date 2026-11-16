"""Recompile every framework that has to be built by hand after a source update."""

import argparse
import subprocess

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_cfg
from scripts.download.frameworks.update_types import ToolSpec
from scripts.shared import consent

# - a source build is minutes of compiler work, so it asks before it starts
BUILD_SECONDS = 900


def build_targets(only: list[str] | None = None) -> list[ToolSpec]:
    return [tool for tool in update_cfg.TOOLS if tool.build_command and (not only or tool.name in only)]


def run_builds(targets: list[ToolSpec], *, foreground: bool = False, dry_run: bool = False) -> int:
    """Build each target where it is installed; returns how many failed."""
    failed = 0
    for tool in targets:
        folder = project_cfg.framework_install_dir(tool.name)
        if not folder.is_dir():
            print(f"[FAIL] {tool.name}: not installed at {folder}", flush=True)
            failed += 1
            continue
        command = subprocess.list2cmdline(list(tool.build_command or []))
        if dry_run:
            print(f"{tool.name}: {command}  (cwd {folder})", flush=True)
            continue
        if foreground:
            print(f"\n=== {tool.name} ===\n{command}", flush=True)
            try:
                subprocess.run(list(tool.build_command or []), cwd=folder, check=True)
            except subprocess.CalledProcessError:
                failed += 1
            continue
        print(f"[BUILD] {tool.name}: new terminal -> {command}", flush=True)
        # - the new window carries its own title and a first line, so a stray console is identifiable
        titled = f"title C:/AI build: {tool.name} && echo [BUILD] {tool.name} && {command}"
        subprocess.Popen(["cmd.exe", "/k", titled], cwd=folder, creationflags=subprocess.CREATE_NEW_CONSOLE)
    if foreground and failed:
        print(f"\n[FAIL] {failed} build(s) failed")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="build only these catalog names")
    parser.add_argument(
        "--foreground", action="store_true", help="Build in this console instead of one new terminal per target."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved commands and stop.")
    consent.flag(parser)
    args = parser.parse_args()
    targets = build_targets(args.only)
    if not targets:
        parser.error("No catalog entry declares a build command")
    if not args.dry_run and not consent.ask("Framework build", BUILD_SECONDS, args.yes):
        return 1
    return 1 if run_builds(targets, foreground=args.foreground, dry_run=args.dry_run) else 0


if __name__ == "__main__":
    raise SystemExit(main())
