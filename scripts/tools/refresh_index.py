"""Rebuild the two code indexes, which nothing else refreshes.

Both indexes are snapshots taken by a command: the desktop profile installs no file watcher, so a
symbol added after the last run reads as missing and an answer about moved code is confidently
wrong. This runs `codebase-memory-mcp` and `graphify` against the tree in parallel and skips
graphify when the commit touched no file it extracts. A commit is never failed by an indexer: a
missing binary prints `[SKIP]` and a crash prints its own exit code.

The procedure and its measured cost are in [CODE-SEARCH](../../.agents/CODE-SEARCH.md).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers.launch_util import describe_exit
from scripts.shared import changes

# - what graphify extracts; a Markdown or YAML commit leaves its graph identical
GRAPHIFY_SUFFIXES = frozenset({".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx"})

# - the shims the two installers write, before PATH is consulted
SHIMS = {"codebase-memory-mcp": "codebase-memory-mcp.exe", "graphify": "graphify.exe"}


@dataclass(frozen=True)
class Step:
    """One index rebuild: a name for the report, its commands, and why it was skipped."""

    name: str
    commands: tuple[tuple[str, ...], ...] = ()
    skip: str = ""
    cwd: str = ""


def binary(name: str) -> str:
    """The executable for one indexer, preferring the shim the installer wrote."""
    shim = Path.home() / ".local" / "bin" / SHIMS[name]
    if shim.is_file():
        return str(shim)
    return shutil.which(name) or ""


def needs_graphify(paths: list[str]) -> bool:
    """Whether the commit changed a file graphify extracts; an unknown change set counts as yes."""
    return not paths or any(Path(path).suffix.lower() in GRAPHIFY_SUFFIXES for path in paths)


def plan(paths: list[str], root: Path, resolve: Callable[[str], str] = binary) -> list[Step]:
    """The index rebuilds this change set calls for."""
    memory = resolve("codebase-memory-mcp")
    steps = [
        Step(
            "codebase-memory",
            ((memory, "--quiet", "cli", "index_repository", "--repo-path", root.as_posix(), "--mode", "fast"),)
            if memory
            else (),
            "" if memory else "codebase-memory-mcp not installed",
            root.as_posix(),
        )
    ]
    tool = resolve("graphify")
    if tool and needs_graphify(paths):
        steps.append(
            Step(
                "graphify",
                (
                    (tool, "update", root.as_posix(), "--no-cluster"),
                    (tool, "cluster-only", root.as_posix(), "--no-label", "--no-viz"),
                ),
                cwd=root.as_posix(),
            )
        )
    elif tool:
        steps.append(Step("graphify", skip="no extracted file in this commit"))
    else:
        steps.append(Step("graphify", skip="graphify not installed"))
    return steps


def run_step(step: Step) -> tuple[Step, float, int, str]:
    """Run one step's commands in order, stopping at the first failure, and time the whole step."""
    started = time.monotonic()
    code, tail = 0, ""
    for command in step.commands:
        result = subprocess.run(list(command), capture_output=True, text=True, check=False, cwd=step.cwd or None)
        code = result.returncode
        tail = (result.stderr or result.stdout).strip().splitlines()[-1] if (result.stderr or result.stdout) else ""
        if code:
            break
    return step, time.monotonic() - started, code, tail


def report(step: Step, seconds: float = 0.0, code: int = 0, tail: str = "") -> None:
    if step.skip:
        print(f"[SKIP] {step.name}: {step.skip}", flush=True)
    elif code:
        print(f"[FAIL] {step.name} {seconds:.1f} s exit {describe_exit(code)}: {tail}", flush=True)
    else:
        print(f"[OK] {step.name} {seconds:.1f} s", flush=True)


def default_paths(root: Path) -> list[str]:
    """What to judge with no change set given: the last commit plus anything uncommitted."""
    return sorted(set(changes.committed_paths(root)) | set(changes.changed_paths(root)))


def refresh(paths: list[str] | None = None, root: Path | None = None) -> int:
    """Rebuild what the change set needs, then report each indexer's own exit code."""
    base = project_cfg.BASE_DIR if root is None else root
    steps = plan(default_paths(base) if paths is None else paths, base)
    with ThreadPoolExecutor(max_workers=len(steps)) as pool:
        outcomes = list(pool.map(run_step, steps))
    for outcome in outcomes:
        report(*outcome)
    return 0 if all(code == 0 for _, _, code, _ in outcomes) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", nargs="*", help="change set to judge; default is HEAD's commit plus the tree")
    args = parser.parse_args(argv)
    return refresh(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
