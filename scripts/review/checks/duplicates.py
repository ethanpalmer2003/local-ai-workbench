"""Verbatim duplicate blocks through pylint's `duplicate-code`, against a reviewed baseline.

Pylint reports a copied block only while it stays textually close, so a renamed copy escapes it; the
semantic [similarity](SIMILARITY.md) check is the one that sees a re-implemented rule. This covers
the other half, the block that really was pasted. It is opt-in because pylint needs about forty
seconds over `scripts`, which does not fit the gate.

A finding is a file pair plus how many blocks that pair shares, so a new block in an already-known
pair still fails. `--update` accepts today's list into the baseline; review it before doing that.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from scripts.config import project_config as project_cfg

BASELINE = project_cfg.SCRIPTS_DIR / "review" / "lists" / "duplicate-baseline.json"
FINDING = re.compile(r"R0801: Similar lines in (\d+) files")
REFERENCE = re.compile(r"^==(?P<module>[\w.]+):\[(?P<start>\d+):(?P<end>\d+)\]$")


def module_paths(root: Path) -> dict[str, str]:
    """Module name to repository-relative path, because pylint reports `==scripts.a.b:[1:2]`."""
    return {
        ".".join(path.relative_to(project_cfg.BASE_DIR).with_suffix("").parts): path.relative_to(
            project_cfg.BASE_DIR
        ).as_posix()
        for path in root.rglob("*.py")
    }


def pair_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def _flush(pending: list[str], modules: dict[str, str], counts: Counter[str]) -> None:
    files = sorted({modules.get(name, name.replace(".", "/") + ".py") for name in pending})
    for index, left in enumerate(files):
        for right in files[index + 1 :]:
            counts[pair_key(left, right)] += 1


def parse(text: str, modules: dict[str, str]) -> Counter[str]:
    """Block count per file pair from pylint's text output."""
    counts: Counter[str] = Counter()
    pending: list[str] = []
    for line in text.splitlines():
        if FINDING.search(line):
            _flush(pending, modules, counts)
            pending = []
            continue
        reference = REFERENCE.match(line.strip())
        if reference:
            pending.append(reference.group("module"))
            continue
        _flush(pending, modules, counts)
        pending = []
    _flush(pending, modules, counts)
    return counts


def run_pylint(root: Path) -> str:
    """Pylint's duplicate report for the tree; a missing executable is a hard failure."""
    executable = project_cfg.VENV_DIR / "Scripts" / "pylint.exe"
    result = subprocess.run(
        [str(executable), "--disable=all", "--enable=duplicate-code", "--score=n", root.as_posix()],
        cwd=project_cfg.BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 8):
        raise RuntimeError(f"pylint exited {result.returncode}: {(result.stderr or result.stdout).strip()[-300:]}")
    return result.stdout


def load_baseline() -> dict[str, int]:
    if not BASELINE.is_file():
        return {}
    return dict(json.loads(BASELINE.read_text(encoding="utf-8"))["pairs"])


def save_baseline(counts: Counter[str]) -> None:
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps({"pairs": dict(sorted(counts.items()))}, indent=2) + "\n", encoding="utf-8")


def unreviewed(counts: Counter[str], baseline: dict[str, int]) -> list[tuple[str, int, int]]:
    """Pairs whose block count grew, as (pair, now, baseline)."""
    return [
        (pair, count, baseline.get(pair, 0)) for pair, count in sorted(counts.items()) if count > baseline.get(pair, 0)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="accept the current list into the baseline")
    parser.add_argument("--path", default=str(project_cfg.SCRIPTS_DIR), help="tree to scan")
    args = parser.parse_args(argv)
    root = Path(args.path)
    counts = parse(run_pylint(root), module_paths(root))
    if args.update:
        save_baseline(counts)
        print(f"[OK] baseline holds {len(counts)} file pair(s) with {sum(counts.values())} block(s)")
        return 0
    fresh = unreviewed(counts, load_baseline())
    for pair, count, known in fresh:
        left, right = pair.split("|")
        print(f"[FAIL] {left} <-> {right}: {count} block(s), baseline {known}")
    if fresh:
        print("[NEXT] fold duplicates into one implementation, or accept them with --update after review")
        return 1
    print(f"[OK] {len(counts)} known pair(s), no new duplicate block")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
