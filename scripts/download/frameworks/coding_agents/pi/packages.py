"""Preview or apply the Pi extension manifest without removing unrelated npm dependencies."""

import argparse
import json
import shutil
import subprocess

from scripts.config import project_config as project_cfg
from scripts.config.coding_agents.pi import packages
from scripts.download.frameworks.npm import command as npm_command
from scripts.file_util import archive_path


def installed_packages() -> set[str]:
    manifest = packages.INSTALL_DIR / "package.json"
    return (
        set(json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})) if manifest.is_file() else set()
    )


def sync_plan() -> tuple[list[str], list[str]]:
    desired = {extension.package for extension in packages.extensions()}
    installed = installed_packages()
    additions = sorted(
        name
        for name in desired
        if name not in installed or not (packages.package_path(name) / "package.json").is_file()
    )
    removals = sorted((packages.managed_names() - desired) & installed)
    return additions, removals


def sync_local_extensions() -> None:
    root = project_cfg.component("coding_agents/pi").state_dir / "agent/extensions"
    root.mkdir(parents=True, exist_ok=True)
    previous = json.loads(packages.STATE_FILE.read_text(encoding="utf-8")) if packages.STATE_FILE.is_file() else {}
    sources = packages.local_extensions()
    names = {source.name for source in sources}
    for name in previous.get("local_extensions", []):
        if name not in names:
            archive_path(root / name, root)
    for source in sources:
        shutil.copy2(source, root / source.name)


def sync(apply: bool = False) -> None:
    additions, removals = sync_plan()
    print("Pi extension manifest: " + str(packages.MANIFEST))
    for group in ("visual", "nonvisual"):
        print(
            group.capitalize() + ": " + ", ".join(item.package for item in packages.extensions() if item.group == group)
        )
    print("Install: " + (", ".join(additions) or "none"))
    print("Uninstall: " + (", ".join(removals) or "none"))
    if not apply:
        print("[OK] Preview only. Use --sync to apply package and active settings changes.")
        return
    prefix = [*npm_command(), "--prefix", str(packages.INSTALL_DIR)]
    if additions:
        subprocess.run([*prefix, "install", "--save-exact", "--no-audit", "--no-fund", *additions], check=True)
    if removals:
        subprocess.run([*prefix, "uninstall", "--no-audit", "--no-fund", *removals], check=True)
    selected = packages.package_paths()
    for settings in (
        project_cfg.component("coding_agents/pi").state_dir / "agent/settings.json",
        packages.INSTALL_DIR / "settings.json",
    ):
        packages.sync_settings(settings, selected)
    sync_local_extensions()
    packages.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    packages.STATE_FILE.write_text(
        json.dumps(
            {
                "managed": [item.package for item in packages.extensions()],
                "local_extensions": [source.name for source in packages.local_extensions()],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("[OK] Pi packages and active settings match the manifest.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Install added packages, uninstall removed managed packages, and update active settings",
    )
    args = parser.parse_args(argv)
    sync(args.sync)


if __name__ == "__main__":
    main()
