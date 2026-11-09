"""Check the installed ComfyUI node loads and keeps the contract its workflow relies on.

ComfyUI's interpreter owns the node's runtime dependencies, so the startup batch runs this
check instead of the scripts suite; the scripts suite still checks the contract offline.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

NODE_CLASS = "LocalLTXCachedTextEncode"
REQUIRED_INPUTS = ("cache_enabled", "clip", "text")
HIDDEN_INPUTS = ("prompt", "unique_id")
# - lazy evaluation is what keeps a cache hit from loading the text encoder at all
LAZY_INPUTS = ("clip",)
CLASS_ATTRIBUTES = ("CATEGORY", "FUNCTION", "RETURN_TYPES")
METHODS = ("IS_CHANGED", "check_lazy_status", "encode")
# - imported inside the node's methods, so a missing module only fails mid-workflow
RUNTIME_MODULES = ("folder_paths", "torch")
# - <installation>/custom_nodes/<node>/__init__.py
INSTALLATION_LEVEL = 2
# - node types the tracked workflows queue, and the custom-node folder that must register them; a
#   type is matched where it is spelled as a NODE_CLASS_MAPPINGS key, since importing the other
#   providers needs ComfyUI's own runtime
REQUIRED_PROVIDERS = {
    "CLIPLoaderGGUF": "ComfyUI-GGUF",
    "CLIPLoaderGGUFDynamicVRAM": "ComfyUI-GGUF",
    "LocalLTXCachedTextEncode": "ltx-prompt-cache",
    "UnetLoaderGGUFDynamicVRAM": "ComfyUI-GGUF",
}


def installation_root(node: Path) -> Path:
    """Installation directory that supplies folder_paths and torch to the node."""
    return node.parents[INSTALLATION_LEVEL] if len(node.parents) > INSTALLATION_LEVEL else node.parent


def load(node: Path) -> ModuleType:
    """Import the installed copy by path, the way ComfyUI's custom-node loader does."""
    name = f"comfyui_node_{node.parent.name.replace('-', '_')}"
    specification = importlib.util.spec_from_file_location(name, node)
    if specification is None or specification.loader is None:
        raise ImportError(f"not loadable as a module: {node}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _class_issues(node: Any) -> list[str]:
    issues = [f"{NODE_CLASS}.{name} is missing" for name in CLASS_ATTRIBUTES if not getattr(node, name, None)]
    issues += [f"{NODE_CLASS}.{name} is not callable" for name in METHODS if not callable(getattr(node, name, None))]
    function = getattr(node, "FUNCTION", "")
    if not callable(getattr(node, function, None)):
        issues.append(f"{NODE_CLASS}.FUNCTION names no method: {function!r}")
    return issues


def _input_issues(node: Any) -> list[str]:
    inputs = node.INPUT_TYPES()
    if not isinstance(inputs, dict):
        return [f"{NODE_CLASS}.INPUT_TYPES did not return a mapping"]
    raw_required, raw_hidden = inputs.get("required"), inputs.get("hidden")
    required = raw_required if isinstance(raw_required, dict) else {}
    hidden = raw_hidden if isinstance(raw_hidden, dict) else {}
    issues = [f"INPUT_TYPES.required lacks {name}" for name in REQUIRED_INPUTS if name not in required]
    issues += [f"INPUT_TYPES.hidden lacks {name}" for name in HIDDEN_INPUTS if name not in hidden]
    for name in LAZY_INPUTS:
        spec = required.get(name)
        options = spec[1] if isinstance(spec, tuple) and len(spec) > 1 else None
        if not isinstance(options, dict) or options.get("lazy") is not True:
            issues.append(f"INPUT_TYPES.required.{name} is not lazy")
    return issues


def _registration_issues(module: ModuleType) -> list[str]:
    display = getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", None)
    if isinstance(display, dict) and NODE_CLASS in display:
        return []
    return [f"NODE_DISPLAY_NAME_MAPPINGS does not name {NODE_CLASS}"]


def contract_issues(module: ModuleType) -> list[str]:
    """Everything ComfyUI needs to queue the node, checked against the loaded module."""
    mapping = getattr(module, "NODE_CLASS_MAPPINGS", None)
    if not isinstance(mapping, dict) or NODE_CLASS not in mapping:
        return [f"NODE_CLASS_MAPPINGS does not register {NODE_CLASS}"]
    node = mapping[NODE_CLASS]
    return [*_class_issues(node), *_input_issues(node), *_registration_issues(module)]


def runtime_issues(root: Path) -> list[str]:
    """Modules the node imports lazily, proved resolvable from ComfyUI's installation."""
    entry = str(root)
    sys.path.insert(0, entry)
    try:
        return [
            f"{name} is not importable from {root}"
            for name in RUNTIME_MODULES
            if importlib.util.find_spec(name) is None
        ]
    finally:
        sys.path.remove(entry)


def _registered(folder: Path, name: str) -> bool:
    pattern = re.compile(rf"""["']{re.escape(name)}["']\s*:""")
    for path in folder.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                return True
        except OSError:
            continue
    return False


def provider_issues(custom_nodes: Path) -> list[str]:
    """Providers that must be present for every node type the tracked workflows queue."""
    issues = []
    for name, folder_name in sorted(REQUIRED_PROVIDERS.items()):
        folder = custom_nodes / folder_name
        if not folder.is_dir():
            issues.append(f"{name}: custom_nodes/{folder_name} is missing")
        elif not _registered(folder, name):
            issues.append(f"{name}: custom_nodes/{folder_name} does not register it")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node", type=Path, help="Installed node copy ComfyUI loads at startup")
    args = parser.parse_args(argv)
    if args.node.is_file():
        issues = runtime_issues(installation_root(args.node))
        issues += provider_issues(args.node.parent.parent)
        try:
            issues += contract_issues(load(args.node))
        except Exception as error:
            # - any import failure is a failed check, not a crashed launcher
            issues.append(f"{type(error).__name__}: {error}")
    else:
        issues = [f"missing installed copy: {args.node}"]
    for issue in issues:
        print(f"[FAIL] {issue}")
    print(f"[{'FAIL' if issues else 'OK'}] ComfyUI node: {args.node}")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
