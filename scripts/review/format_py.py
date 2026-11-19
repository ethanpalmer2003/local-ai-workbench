"""Format the Python this change touched; `--all` formats the whole repository."""

import argparse
import subprocess

from scripts.config import project_config as project_cfg
from scripts.review.__main__ import changed_since_upstream


def python_targets(all_files: bool) -> list[str]:
    """Changed Python files that still exist, or the repository root when nothing changed or --all is given."""
    if all_files:
        return ["."]
    files = [
        path for path in changed_since_upstream() if path.endswith(".py") and (project_cfg.BASE_DIR / path).is_file()
    ]
    return files or ["."]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="format every tracked Python file, not just the change")
    args = parser.parse_args(argv)
    targets = python_targets(args.all)
    print(f"[FORMAT] {len(targets)} target(s)", flush=True)
    return subprocess.run(
        [
            str(project_cfg.VENV_DIR / "Scripts" / "ruff.exe"),
            "format",
            "--config",
            str(project_cfg.BASE_DIR / "pyproject.toml"),
            *targets,
        ],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
