"""One Pi package manifest shared by launchers, updater and the explicit sync command."""

import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.config.coding_agents.pi import inventory

MANIFEST = Path(inventory.__file__)
INSTALL_NAME = "coding_agents/pi"
INSTALL_DIR = project_cfg.component(INSTALL_NAME).framework_dir
STATE_FILE = project_cfg.component(INSTALL_NAME).state_dir / "packages.json"
LEGACY_PACKAGES = ("pi-lsp-extension", "pi-lsp")
PACKAGE_NAME = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class PiExtension:
    package: str
    enabled: bool
    cli_args: tuple[str, ...]
    environment: dict[str, str]
    group: str = "nonvisual"


def manifest() -> dict[str, Any]:
    data = deepcopy(inventory.CONFIG)
    if not PACKAGE_NAME.fullmatch(data["core_package"]):
        raise ValueError("Invalid Pi core package name")
    return data


def extensions(include_disabled: bool = False) -> tuple[PiExtension, ...]:
    data = manifest()
    result = []
    seen = {data["core_package"]}
    for entry in data["extensions"]:
        name = entry["package"]
        if not PACKAGE_NAME.fullmatch(name) or name in seen:
            raise ValueError(f"Invalid or duplicate Pi extension package: {name!r}")
        seen.add(name)
        args = entry.get("cli_args", [])
        environment = entry.get("environment", {})
        if not isinstance(args, list) or not isinstance(environment, dict):
            raise ValueError(f"Pi extension cli_args must be a list and environment an object: {name}")
        if not all(isinstance(arg, str) for arg in args) or not all(
            isinstance(value, str) for value in environment.values()
        ):
            raise ValueError(f"Pi extension arguments and environment must be strings: {name}")
        enabled = entry.get("enabled", True)
        group = entry.get("group", "nonvisual")
        if group not in ("visual", "nonvisual"):
            raise ValueError(f"Invalid Pi extension group: {name}")
        if not isinstance(enabled, bool):
            raise ValueError(f"Pi extension enabled must be true or false: {name}")
        if enabled or include_disabled:
            result.append(PiExtension(name, enabled, tuple(args), environment, group))
    return tuple(result)


def package_path(name: str) -> Path:
    if not PACKAGE_NAME.fullmatch(name):
        raise ValueError(f"Invalid Pi package name: {name!r}")
    return INSTALL_DIR / "node_modules" / name


def package_paths() -> tuple[Path, ...]:
    return tuple(package_path(extension.package) for extension in extensions())


def cli_args() -> tuple[str, ...]:
    return tuple(arg for extension in extensions() for arg in extension.cli_args)


def local_extensions() -> tuple[Path, ...]:
    root = MANIFEST.parent.resolve()
    paths = tuple((root / value).resolve() for value in manifest()["local_extensions"])
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError("Pi local extension paths must stay under scripts/config/pi")
    return paths


def managed_names() -> set[str]:
    previous = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("managed", []) if STATE_FILE.is_file() else []
    names = {*LEGACY_PACKAGES, *previous, *(extension.package for extension in extensions(True))}
    return {name for name in names if PACKAGE_NAME.fullmatch(name) and name != manifest()["core_package"]}


def managed_package_reference(value: object) -> bool:
    source = value.get("source", "") if isinstance(value, dict) else value
    if not isinstance(source, str):
        return False
    source = source.replace("\\", "/").rstrip("/")
    return any(re.search(r"(?:^|/|npm:)" + re.escape(name) + r"(?:@[^/]*)?$", source) for name in managed_names())


def variables(inherited: dict[str, str]) -> dict[str, str]:
    return {
        "config_dir": project_cfg.CONFIG_DIR.as_posix(),
        "state_dir": project_cfg.STATE_DIR.as_posix(),
        "venv": project_cfg.VENV_DIR.as_posix(),
        "path_separator": os.pathsep,
        "PATH": inherited.get("PATH", ""),
    }


def environment(selected: tuple[Path, ...], inherited: dict[str, str]) -> dict[str, str]:
    substitutions = variables(inherited)
    selected_paths = {path.resolve() for path in selected}
    values = {}
    for extension in extensions():
        if package_path(extension.package).resolve() in selected_paths:
            values.update({name: value.format_map(substitutions) for name, value in extension.environment.items()})
    return values


def sync_settings(path: Path, selected: tuple[Path, ...]) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["packages"] = [value for value in data.get("packages", []) if not managed_package_reference(value)]
    data["packages"].extend(package.as_posix() for package in selected)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(manifest()))
