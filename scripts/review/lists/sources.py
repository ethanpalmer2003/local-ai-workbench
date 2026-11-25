"""The files a check reads: maintained Python, Markdown and batch sources."""

from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.shared.file_sets import maintained_files


def check_targets(argv: list[str] | None, suffixes: tuple[str, ...]) -> list[Path]:
    """The files a section reads: its positional arguments when given, otherwise the whole tree.

    A section takes repo-relative paths so the scoped run reads only the change, while the full run
    passes nothing and keeps its whole-tree guarantee.
    """
    if argv:
        return [project_cfg.BASE_DIR / path for path in argv]
    return [path for path in maintained_files() if path.suffix in suffixes]
