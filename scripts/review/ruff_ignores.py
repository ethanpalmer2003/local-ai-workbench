"""Count ruff suppressions: global ignores, per-file ignores and inline `noqa` comments."""

import argparse
import io
import tokenize
import tomllib
from pathlib import Path
from typing import TypedDict

from scripts.config import project_config as project_cfg

NOQA = "# noqa"


class Configuration(TypedDict):
    select: list[str]
    ignore: list[str]
    per_file: dict[str, list[str]]
    per_file_entries: int
    per_file_patterns: int


class Report(Configuration):
    inline_files: list[str]
    total_entries: int
    rules: list[str]


def configuration(path: Path | None = None) -> Configuration:
    """The ruff lint configuration this project loads."""
    source = path or (project_cfg.BASE_DIR / "pyproject.toml")
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    lint = data.get("tool", {}).get("ruff", {}).get("lint", {})
    per_file: dict[str, list[str]] = dict(lint.get("per-file-ignores", {}))
    return {
        "select": list(lint.get("select", [])),
        "ignore": list(lint.get("ignore", [])),
        "per_file": per_file,
        "per_file_entries": sum(len(rules) for rules in per_file.values()),
        "per_file_patterns": len(per_file),
    }


def inline(paths: list[Path] | None = None) -> list[str]:
    """Files that carry an inline `noqa`; every suppression belongs in pyproject instead."""
    found: list[str] = []
    for path in sorted((project_cfg.BASE_DIR / "scripts").rglob("*.py")) if paths is None else paths:
        if "state" in path.parts or "retired" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        comments = [
            token.string
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        ]
        if any(NOQA in comment for comment in comments):
            try:
                found.append(path.relative_to(project_cfg.BASE_DIR).as_posix())
            except ValueError:
                # - a caller can hand in a scratch file outside the repository
                found.append(path.as_posix())
    return found


def report() -> Report:
    """Every suppression source with its size, so growth is visible in one place."""
    settings = configuration()
    per_file = settings["per_file"]
    rules = sorted({rule for rules in per_file.values() for rule in rules} | set(settings["ignore"]))
    return {
        **settings,
        "inline_files": inline(),
        "total_entries": len(settings["ignore"]) + settings["per_file_entries"],
        "rules": rules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="list every per-file pattern and its rules")
    args = parser.parse_args(argv)
    value = report()
    print(f"selected families: {', '.join(value['select'])}")
    print(f"global ignores: {len(value['ignore'])} ({', '.join(value['ignore']) or 'none'})")
    print(f"per-file patterns: {value['per_file_patterns']} carrying {value['per_file_entries']} entries")
    if args.verbose:
        for pattern, rules in value["per_file"].items():
            print(f"  {pattern}: {', '.join(rules)}")
    print(f"inline noqa files: {len(value['inline_files'])}")
    print(f"total suppression entries: {value['total_entries']}")
    print(f"rules suppressed somewhere: {', '.join(value['rules'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
