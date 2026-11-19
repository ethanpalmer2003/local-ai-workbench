"""Find files by suffix under the repository's known roots, without walking the whole data tree.

`python -m scripts.tools.locate_files .gguf` answers "where are the weights" in a bounded depth, so no
caller needs a recursive scan of `data/` or `frameworks/`.
"""

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from scripts.config import project_config as project_cfg

# - deep enough for the Hugging Face cache layout (root/models--owner--repo/snapshots/<rev>/file)
DEFAULT_DEPTH = 4
# - the roots that hold installs and weights, in the order a caller usually wants them
KNOWN_ROOTS = (project_cfg.HF_MODELS_DIR, project_cfg.FRAMEWORKS_DIR)


def locate(suffixes: Sequence[str], roots: Iterable[Path] = KNOWN_ROOTS, depth: int = DEFAULT_DEPTH) -> list[Path]:
    """Return files under `roots` whose name ends with one of `suffixes`, stopping at `depth` levels."""
    wanted = tuple(suffix.lower() for suffix in suffixes)
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(_walk(root, wanted, depth))
    return sorted(found)


def _walk(root: Path, suffixes: tuple[str, ...], depth: int) -> list[Path]:
    """Collect matching files below `root`; a directory at the depth limit is not entered."""
    if depth <= 0:
        return []
    found: list[Path] = []
    for entry in root.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            found.extend(_walk(entry, suffixes, depth - 1))
        elif entry.name.lower().endswith(suffixes):
            found.append(entry)
    return found


def main(arguments: Sequence[str] | None = None) -> int:
    """Print one matching path per line; exit 1 when nothing matches."""
    parser = argparse.ArgumentParser(description="List files by suffix under the known roots.")
    parser.add_argument("suffixes", nargs="+", help="file suffixes such as .gguf or .safetensors")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH, help=f"levels to descend, default {DEFAULT_DEPTH}")
    options = parser.parse_args(arguments)
    matches = locate(options.suffixes, depth=options.depth)
    for path in matches:
        print(f"{path}  {path.stat().st_size / 1_000_000:.0f} MB")
    if not matches:
        print(f"no file under {', '.join(str(root) for root in KNOWN_ROOTS)} ends with {', '.join(options.suffixes)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
