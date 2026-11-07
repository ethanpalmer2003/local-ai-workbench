"""Recompile every framework that has to be built by hand after a source update."""

import argparse
import subprocess

from scripts.config import project_config as project_cfg
from scripts.download.frameworks import framework_catalog as update_cfg
from scripts.download.frameworks.update_types import ToolSpec


def build_targets(only: list[str] | None = None) -> list[ToolSpec]:
    return [tool for tool in update_cfg.TOOLS if tool.build_command and (not only or tool.name in only)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="build only these catalog names")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Build in this console instead of one new terminal per target.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved commands and stop.")
    args = parser.parse_args()
    targets = build_targets(args.only)
    if not targets:
        parser.error("No catalog entry declares a build command")
    failed = 0
    for tool in targets:
        folder = project_cfg.framework_install_dir(tool.name)
        if not folder.is_dir():
            print(f"[FAIL] {tool.name}: not installed at {folder}", flush=True)
            failed += 1
            continue
        command = subprocess.list2cmdline(list(tool.build_command))
        if args.dry_run:
            print(f"{tool.name}: {command}  (cwd {folder})", flush=True)
            continue
        if args.foreground:
            print(f"\n=== {tool.name} ===\n{command}", flush=True)
            try:
                subprocess.run(list(tool.build_command), cwd=folder, check=True)
            except subprocess.CalledProcessError:
                failed += 1
            continue
        print(f"[BUILD] {tool.name}: new terminal -> {command}", flush=True)
        subprocess.Popen(["cmd.exe", "/k", *tool.build_command], cwd=folder, creationflags=subprocess.CREATE_NEW_CONSOLE)
    if args.foreground and failed:
        print(f"\n[FAIL] {failed} build(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
