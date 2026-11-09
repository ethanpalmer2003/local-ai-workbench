"""Inventory ROCm installs on this machine: location, kind, version, size and project references.

Read-only. Scans the AMD program folder, the data runtime folder, framework `rocm` folders and the
AudioCpp ROCm additions, then reports which of them the project configuration actually points at.
"""

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from scripts.config import project_config as project_cfg

AMD_ROOT = Path(r"C:\Program Files\AMD\ROCm")
MARKERS = ("amdhip64.dll", "amdhip64_7.dll", "hipblas.dll", "hipblaslt.dll", "libhipblaslt.dll", "rocblas.dll")
VERSION_FILES = (".hipVersion", "bin/.hipVersion")


@dataclass
class Install:
    root: str
    kind: str
    version: str
    size: str
    size_bytes: int
    files: int
    modified: str
    on_path: bool
    used_by: str


def _has_marker(directory: Path) -> bool:
    return any((directory / marker).is_file() or (directory / "bin" / marker).is_file() for marker in MARKERS)


def is_rocm(root: Path) -> bool:
    return root.is_dir() and _has_marker(root)


def kind_of(root: Path) -> str:
    if (root / "bin" / "clang++.exe").is_file() or (root / "lib" / "llvm" / "bin" / "clang++.exe").is_file():
        return "sdk install"
    if (root / "BUILD.json").is_file() or (root / ".release_asset").is_file():
        return "bundled build"
    return "runtime libs"


def _marker_version(text: str) -> str:
    """A HIP version marker is either one version line or shell-style HIP_VERSION_* variables."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    major, minor = fields.get("HIP_VERSION_MAJOR"), fields.get("HIP_VERSION_MINOR")
    if major and minor:
        return ".".join(part for part in (major, minor, fields.get("HIP_VERSION_PATCH")) if part)
    return next((line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")), "")


def version_of(root: Path) -> str:
    for relative in VERSION_FILES:
        marker = root / relative
        if marker.is_file():
            text = _marker_version(marker.read_text(encoding="utf-8", errors="replace"))
            if text:
                return text
    build = root / "BUILD.json"
    if build.is_file():
        try:
            value = json.loads(build.read_text(encoding="utf-8")).get("rocm_version")
        except (OSError, json.JSONDecodeError):
            value = None
        if value:
            return str(value)
    return root.name


def _size(root: Path) -> tuple[int, int]:
    total, files = 0, 0
    for item in root.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
                files += 1
        except OSError:
            continue
    return total, files


def _modified(root: Path) -> str:
    try:
        return datetime.fromtimestamp(root.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "-"


def _on_path(root: Path) -> bool:
    entries = {entry.lower().rstrip("\\") for entry in os.environ.get("PATH", "").split(os.pathsep)}
    return str(root).lower() in entries or str(root / "bin").lower() in entries


def references() -> dict[Path, str]:
    """Project paths that load from a ROCm install, with the component that uses them."""
    return {
        project_cfg.ROCM_SDK_BIN_DIR.parent: "sd.cpp and AudioCpp rocm-release",
        project_cfg.AUDIOCPP_ROCM_BUILD_DIR: "AudioCpp hip build",
        project_cfg.AUDIOCPP_ROCM_LEGACY_DIR: "AudioCpp legacy hip build",
        project_cfg.AUDIOCPP_ROCM_DIR: "AudioCpp release zip",
        project_cfg.SDCPP_ROCM_DIR: "sd.cpp runtime folder",
        project_cfg.LLAMACPP_ROCM_LEMONADE_DIR: "llama.cpp rocm-lemonade build",
    }


def _users(root: Path, known: dict[Path, str]) -> str:
    target = root.resolve()
    labels = []
    for path, label in known.items():
        try:
            other = path.resolve()
        except OSError:
            continue
        if target == other or target in other.parents or other in target.parents:
            labels.append(label)
    return ", ".join(dict.fromkeys(labels))


def candidate_roots() -> list[Path]:
    candidates: list[Path] = []
    for container in (AMD_ROOT, project_cfg.DATA_DIR / "ROCm", project_cfg.AUDIOCPP_FRAMEWORK_DIR / "additions/rocm"):
        if container.is_dir():
            candidates.extend(sorted(item for item in container.iterdir() if item.is_dir()))
    frameworks = project_cfg.FRAMEWORKS_DIR
    if frameworks.is_dir():
        for folder in sorted(frameworks.iterdir()):
            rocm = folder / "rocm"
            if not rocm.is_dir():
                continue
            if is_rocm(rocm):
                candidates.append(rocm)
            else:
                candidates.extend(sorted(item for item in rocm.iterdir() if item.is_dir() and is_rocm(item)))
    seen: set[str] = set()
    unique = []
    for root in candidates:
        key = str(root.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _human(value: int) -> str:
    if value <= 0:
        return "-"
    scaled = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if scaled < 1024 or unit == "GiB":
            return f"{scaled:.1f} {unit}" if unit != "B" else f"{value} B"
        scaled /= 1024.0
    return f"{scaled:.1f} GiB"


def inventory(roots: list[Path], known: dict[Path, str] | None = None, sizes: bool = True) -> list[Install]:
    known = references() if known is None else known
    found: list[Install] = []
    for root in roots:
        if not is_rocm(root):
            continue
        total, files = _size(root) if sizes else (0, 0)
        found.append(
            Install(
                root=str(root),
                kind=kind_of(root),
                version=version_of(root),
                size=_human(total) if sizes else "-",
                size_bytes=total,
                files=files,
                modified=_modified(root),
                on_path=_on_path(root),
                used_by=_users(root, known),
            )
        )
    return found


def _print(rows: list[Install]) -> None:
    print(f"{'root':<68} {'kind':<14} {'version':<10} {'size':>9} {'files':>7} {'path':<6} used by")
    for row in rows:
        print(
            f"{row.root:<68} {row.kind:<14} {row.version:<10} {row.size:>9} {row.files:>7} "
            f"{'yes' if row.on_path else '-':<6} {row.used_by or '-'}"
        )
    total = sum(row.size_bytes for row in rows)
    referenced = [row for row in rows if row.used_by]
    unreferenced = [row for row in rows if not row.used_by]
    print(
        f"\n{len(rows)} ROCm install(s), about {total / 1024**3:.1f} GiB in total; "
        f"{len(referenced)} referenced by this project, {len(unreferenced)} with no configured reference"
    )


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable rows")
    parser.add_argument("--no-sizes", action="store_true", help="Skip walking each tree, for a fast list")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    rows = inventory(candidate_roots(), sizes=not args.no_sizes)
    if args.json:
        print(json.dumps([asdict(row) for row in rows], indent=2))
        return 0
    _print(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
