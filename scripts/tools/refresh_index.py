"""Rebuild the two code indexes, which nothing else refreshes.

Both indexes are snapshots taken by a command: the desktop profile installs no file watcher, so a
symbol added after the last run reads as missing and an answer about moved code is confidently
wrong. The call graph is cheap, so it is rebuilt before the commit returns. The architecture graph
costs about 25 s whatever changed, so it is started detached with a lock and finishes after the
prompt is back; a docs-only commit skips it. A commit is never failed by an indexer: a missing
binary prints `[SKIP]` and a crash writes its exit code to the run log.

The procedure and its measured cost are in [CODE-SEARCH](../../.agents/CODE-SEARCH.md).
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers.launch_util import describe_exit
from scripts.shared import changes

# - what graphify extracts; a Markdown or YAML commit leaves its graph identical
GRAPHIFY_SUFFIXES = frozenset({".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx"})

# - the shims the two installers write, before PATH is consulted
SHIMS = {"codebase-memory-mcp": "codebase-memory-mcp.exe", "graphify": "graphify.exe"}

# - a background run that outlives this bound was killed, so the next refresh may take the lock
LOCK_STALE_SECONDS = 900

# - the background run needs no console at all, and its own process group so a Ctrl-C misses it
CREATE_NEW_PROCESS_GROUP = 0x00000200


@dataclass(frozen=True)
class Step:
    """One inline rebuild: a name for the report, its commands, and why it was skipped."""

    name: str
    commands: tuple[tuple[str, ...], ...] = ()
    skip: str = ""
    cwd: str = ""


@dataclass(frozen=True)
class Plan:
    """What one refresh does: the call graph now, the architecture graph in the background."""

    memory: Step
    graphify: tuple[tuple[str, ...], ...] = ()
    graphify_skip: str = ""


def binary(name: str) -> str:
    """The executable for one indexer, preferring the shim the installer wrote."""
    shim = Path.home() / ".local" / "bin" / SHIMS[name]
    if shim.is_file():
        return str(shim)
    return shutil.which(name) or ""


def needs_graphify(paths: Sequence[str]) -> bool:
    """Whether the commit changed a file graphify extracts; an unknown change set counts as yes."""
    return not paths or any(Path(path).suffix.lower() in GRAPHIFY_SUFFIXES for path in paths)


def graphify_commands(tool: str, root: Path) -> tuple[tuple[str, ...], ...]:
    """The two passes graphify needs: extract, then re-cluster so hubs and communities stay current.

    `graphify-out` at the root is a junction into `scripts/state/cache`, so an incremental update keeps
    writing the canonical path while the generated files stay in the cache tree.
    """
    return (
        (tool, "update", root.as_posix(), "--no-cluster"),
        (tool, "cluster-only", root.as_posix(), "--no-label", "--no-viz"),
    )


def plan(paths: Sequence[str], root: Path, resolve: Callable[[str], str] = binary) -> Plan:
    """The rebuilds this change set calls for."""
    memory = resolve("codebase-memory-mcp")
    step = Step(
        "codebase-memory",
        ((memory, "--quiet", "cli", "index_repository", "--repo-path", root.as_posix(), "--mode", "fast"),)
        if memory
        else (),
        "" if memory else "codebase-memory-mcp not installed",
        root.as_posix(),
    )
    tool = resolve("graphify")
    if not tool:
        return Plan(step, (), "graphify not installed")
    if not needs_graphify(paths):
        return Plan(step, (), "no extracted file in this commit")
    return Plan(step, graphify_commands(tool, root))


def _run_commands(commands: Sequence[Sequence[str]], cwd: str | None) -> tuple[int, str]:
    """Run commands in order, stopping at the first failure; the exit code and its last output line."""
    code, tail = 0, ""
    for command in commands:
        result = subprocess.run(list(command), capture_output=True, text=True, check=False, cwd=cwd)
        code = result.returncode
        output = (result.stderr or result.stdout).strip()
        tail = output.splitlines()[-1] if output else ""
        if code:
            break
    return code, tail


def run_step(step: Step) -> tuple[Step, float, int, str]:
    """Run one step's commands in order, stopping at the first failure, and time the whole step."""
    started = time.monotonic()
    code, tail = _run_commands(step.commands, step.cwd or None)
    return step, time.monotonic() - started, code, tail


def report(step: Step, seconds: float = 0.0, code: int = 0, tail: str = "") -> None:
    if step.skip:
        print(f"[SKIP] {step.name}: {step.skip}", flush=True)
    elif code:
        print(f"[FAIL] {step.name} {seconds:.1f} s exit {describe_exit(code)}: {tail}", flush=True)
    else:
        print(f"[OK] {step.name} {seconds:.1f} s", flush=True)


def lock_path(root: Path) -> Path:
    return root / "scripts" / "state" / "cache" / "shared" / "index-refresh.lock"


def log_path(root: Path) -> Path:
    return root / "scripts" / "state" / "logs" / "shared" / "index-refresh.log"


def acquire(lock: Path) -> bool:
    """Whether this process owns the lock; a lock older than the bound was abandoned by a killed run."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            lock.touch(exist_ok=False)
            return True
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                # - the run that held it removed it between the failed touch and the read
                continue
            if age < LOCK_STALE_SECONDS:
                return False
            lock.unlink(missing_ok=True)
    return False


def start_graphify(root: Path, lock: Path) -> str:
    """Start the architecture rebuild detached, so the commit returns first; returns the run log path."""
    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "scripts.tools.refresh_index", "--graphify-only", "--lock", str(lock)]
    command.append(root.as_posix())
    with log.open("ab") as sink:
        # - the run says what it is in its own log, because the window it runs in has no text
        sink.write(f"[START] graphify {root.as_posix()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
        sink.flush()
        if os.name == "nt":
            subprocess.Popen(
                command,
                cwd=root.as_posix(),
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
            )
        else:
            subprocess.Popen(
                command,
                cwd=root.as_posix(),
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    return str(log)


def run_graphify(commands: Sequence[Sequence[str]], root: Path, lock: Path | None = None) -> int:
    """Run the architecture rebuild in this process and release the lock whoever ends it."""
    started = time.monotonic()
    try:
        code, tail = _run_commands(commands, root.as_posix())
    finally:
        if lock is not None:
            lock.unlink(missing_ok=True)
    report(Step("graphify"), time.monotonic() - started, code, tail)
    return code


def default_paths(root: Path) -> list[str]:
    """What to judge with no change set given: the last commit plus anything uncommitted.

    A branch with no upstream has nothing to compare against, so its last commit is the whole answer there;
    an indexer must not fail a commit just because the branch is new.
    """
    uncommitted: list[str] = []
    try:
        uncommitted = changes.changed_since_upstream(root)
    except changes.NoUpstreamError:
        uncommitted = []
    return sorted(set(changes.committed_paths(root)) | set(uncommitted))


def refresh(paths: list[str] | None = None, root: Path | None = None) -> int:
    """Rebuild the call graph, start the architecture graph detached, and report each exit code."""
    base = project_cfg.BASE_DIR if root is None else root
    for_commit = plan(default_paths(base) if paths is None else paths, base)
    _memory, seconds, code, tail = run_step(for_commit.memory)
    report(for_commit.memory, seconds, code, tail)
    if not for_commit.graphify:
        report(Step("graphify", skip=for_commit.graphify_skip))
        return 0 if code == 0 else 1
    lock = lock_path(base)
    if not acquire(lock):
        report(Step("graphify", skip="a refresh is already running"))
    else:
        print(f"[START] graphify in background: {start_graphify(base, lock)}", flush=True)
    return 0 if code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", nargs="*", help="change set to judge; default is HEAD's commit plus the tree")
    parser.add_argument("--graphify-only", action="store_true", help="run the architecture rebuild here")
    parser.add_argument("--lock", help="lock file this process removes when the rebuild ends")
    parser.add_argument("root", nargs="?", help="repository root; defaults to this checkout")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    if args.graphify_only:
        base = root or project_cfg.BASE_DIR
        commands = graphify_commands(binary("graphify"), base)
        return run_graphify(commands, base, Path(args.lock) if args.lock else None)
    return refresh(args.paths, root)


if __name__ == "__main__":
    raise SystemExit(main())
