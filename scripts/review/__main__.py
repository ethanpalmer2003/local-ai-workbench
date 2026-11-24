"""Run the repository structure, type and size/complexity reviews."""

import argparse
import contextlib
import io
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple, TextIO

from scripts.config import project_config as project_cfg
from scripts.review.audit import package_audit
from scripts.review.audit.public_audit import main as public_audit_main
from scripts.review.checks import (
    annotations,
    bare_any,
    comments,
    dead_code,
    docs,
    dynamic_imports,
    expression,
    frontend_wiring,
    inventory_code,
    layout,
    line_length,
    model_references,
    network_timeouts,
    overlay_access,
    owned_tokens,
    spellings,
    typography,
    walrus,
)
from scripts.review.lists import text_files
from scripts.shared import changes
from scripts.shared.changes import GitError, NoUpstreamError, changed_since_head, changed_since_upstream
from scripts.shared.import_graph import (
    REACH_DEPTH,
    find_affected_modules,
    git_module_files,
    import_graph,
    module_names,
    module_paths,
)
from scripts.tools import cleanup
from scripts.tools.state_cleanup import prune_generated

SPELL_EXCLUDED = (
    "data/",
    "frameworks/",
    "trash/",
    "scripts/state/",
    "scripts/tests/output/",
    "scripts/benchmarks/output/",
)
TIMES: list[dict[str, Any]] = []
# - basedpyright threads on the whole project: six measured fastest on this 12-core box, at about two thirds
#   of one thread
TYPE_THREADS = 6
# - wall clock from the first section to the last, since concurrent sections sum to more than the wait
_started_at = 0.0


def _spelling_targets() -> list[str]:
    """Tracked Python and Markdown only; generated evidence and vendors stay out of the dictionary."""
    listed = subprocess.run(
        ["git", "-C", str(project_cfg.BASE_DIR), "ls-files", "*.py", "*.md"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    return [item for item in listed if item and not item.startswith(SPELL_EXCLUDED)]


def spelling_check(paths: list[str] | None = None) -> int:
    """Codespell over the change at edit time and the whole tree at push."""
    checker = project_cfg.VENV_DIR / "Scripts" / "codespell.exe"
    # - the same suffix vocabulary as the text checks: an imported patch keeps the upstream spelling
    targets = [path for path in paths if text_files.is_text(path)] if paths else _spelling_targets()
    status = 0
    for start in range(0, len(targets), 80):
        status |= subprocess.run(
            [str(checker), "--ignore-words=.codespell-ignore.txt", "--count", *targets[start : start + 80]],
            cwd=project_cfg.BASE_DIR,
            check=False,
        ).returncode
    return status


def security_audit() -> tuple[int, str]:
    """Advisory count for the installed environment; an unreachable feed is a warning, not a defect."""
    checker = project_cfg.VENV_DIR / "Scripts" / "pip-audit.exe"
    result = subprocess.run(
        [str(checker), "--local", "--progress-spinner", "off", "--format", "json"],
        cwd=project_cfg.BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0, "[WARN] Advisory feed unreachable; nothing was checked"
    findings = sum(len(dep.get("vulns") or []) for dep in report.get("dependencies", []))
    if not findings:
        return 0, "[OK] No known advisories"
    return 1, f"[FAIL] {findings} known advisor{'y' if findings == 1 else 'ies'} in the installed environment"


def declaration_check() -> int:
    """deptry: every import is covered by a declared dependency, and no declaration is unused."""
    checker = project_cfg.VENV_DIR / "Scripts" / "deptry.exe"
    return subprocess.run([str(checker), "scripts"], cwd=project_cfg.BASE_DIR, check=False).returncode


def lock_check() -> int:
    """The lock issues, printed where they are found, so one status reaches the timing log."""
    issues = package_audit.lock_issues()
    for issue in issues[:10]:
        print(f"[FAIL] {issue}")
    print("[OK] uv.lock matches pyproject" if not issues else f"[FAIL] {len(issues)} lock issue(s)")
    return int(bool(issues))


def lint_check() -> int:
    """ruff lint: the configured rule set, including the McCabe limit."""
    checker = project_cfg.VENV_DIR / "Scripts" / "ruff.exe"
    return subprocess.run(
        [str(checker), "check", "--config", str(project_cfg.BASE_DIR / "pyproject.toml"), "."],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


def format_check(paths: list[str] | None = None) -> int:
    """ruff format --check over the tree, or over the change when the edit level passes paths."""
    checker = project_cfg.VENV_DIR / "Scripts" / "ruff.exe"
    targets = list(paths) if paths else ["."]
    return subprocess.run(
        [str(checker), "format", "--check", "--config", str(project_cfg.BASE_DIR / "pyproject.toml"), *targets],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


def type_check(fast: bool) -> int:
    """basedpyright; the slowest section, so --fast skips it."""
    if fast:
        print("\n=== TYPE CHECK ===\n[SKIP] --fast")
        return 0
    print("\n=== TYPE CHECK ===", flush=True)
    checker = project_cfg.VENV_DIR / "Scripts" / "basedpyright.exe"
    try:
        result = subprocess.run(
            [str(checker), "--level", "error", "--threads", str(TYPE_THREADS)],
            cwd=project_cfg.BASE_DIR,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        print(f"[FAIL] Could not run basedpyright at {checker}: {error}")
        return 1
    # - captured, so the section's output lands in its own buffer rather than straight on the terminal
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    return result.returncode


def scoped_type_check(paths: list[str], fast: bool) -> int:
    """basedpyright on what the change reaches: its modules and their direct importers.

    Anything further away cannot have been broken by this change, and the full project runs at push.
    A reach covering most of the tree costs less as one whole-project run, so it falls back to that.
    """
    if fast:
        print("\n=== TYPE CHECK ===\n[SKIP] --fast")
        return 0
    print("\n=== TYPE CHECK ===", flush=True)
    modules = module_names(paths)
    known = git_module_files()
    if not modules:
        return 0
    reachable = find_affected_modules(import_graph(), modules, depth=REACH_DEPTH)
    if len(reachable) * 2 > len(known):
        return type_check(fast)
    checker = project_cfg.VENV_DIR / "Scripts" / "basedpyright.exe"
    targets = module_paths(reachable)
    print(f"[SCOPE] types: {len(targets)} of {len(known)} modules, the change and its direct importers")
    try:
        return subprocess.run(
            [str(checker), "--level", "error", *targets], cwd=project_cfg.BASE_DIR, check=False
        ).returncode
    except OSError as error:
        print(f"[FAIL] Could not run basedpyright at {checker}: {error}")
        return 1


def inventory_check(counts: dict[str, int], fast: bool, paths: list[str] | None = None) -> int:
    """Folder and function inventory; it writes a report, so --fast skips it."""
    if fast:
        return 0
    print("\n=== REPOSITORY INVENTORY ===", flush=True)
    return inventory_code.main(counts, None if paths is None else [project_cfg.BASE_DIR / path for path in paths])


def advisory_check(fast: bool) -> int:
    """Installed-package advisories; the only section that needs the network, so --fast skips it."""
    if fast:
        print("\n=== DEPENDENCY ADVISORIES ===\n[SKIP] --fast")
        return 0
    print("\n=== DEPENDENCY ADVISORIES ===", flush=True)
    status, note = security_audit()
    print(note)
    return status


def timed[T](name: str, function: Callable[..., T], *args: object) -> T | int:
    """Run one gate section and keep its duration, so history answers cost questions without a rerun.

    A section that raises is a failed section rather than a lost run, so the failure is printed and the
    timing log still records which one it was.
    """
    started = time.perf_counter()
    try:
        status = function(*args)
    except Exception as error:  # - a broken section must not take the whole gate down with it
        print(f"[FAIL] {name} raised {type(error).__name__}: {error}")
        status = 1
    TIMES.append({"section": name, "seconds": round(time.perf_counter() - started, 2), "status": status})
    return status


# - sections that share nothing and mostly wait rather than compute, so they run together and print in order
CONCURRENT = ("types", "inventory", "dead code", "line length", "single-owner tokens", "docs", "spelling")


class _ThreadStream(io.TextIOBase):
    """Standard output that a thread can redirect on its own, so concurrent sections do not interleave."""

    def __init__(self, fallback: TextIO) -> None:
        self._fallback = fallback
        self._local = threading.local()

    def write(self, text: str) -> int:
        return self._target().write(text)

    def flush(self) -> None:
        self._target().flush()

    def _target(self) -> TextIO:
        return getattr(self._local, "buffer", None) or self._fallback

    @contextlib.contextmanager
    def collecting(self) -> Iterator[io.StringIO]:
        """Capture this thread's writes into a buffer instead of the terminal."""
        buffer = io.StringIO()
        self._local.buffer = buffer
        try:
            yield buffer
        finally:
            self._local.buffer = None


def run_alongside(
    name: str, function: Callable[[], int], stream: _ThreadStream, outcomes: dict[str, tuple[int, str]]
) -> None:
    """Run one concurrent section with its output captured, recording its duration and status."""
    started = time.perf_counter()
    try:
        with stream.collecting() as buffer:
            status = function()
    except Exception as error:  # - a section that raises is a failed section, not a lost thread
        status = 1
        with stream.collecting() as buffer:
            print(f"[FAIL] {name} raised {type(error).__name__}: {error}")
    TIMES.append({"section": name, "seconds": round(time.perf_counter() - started, 2), "status": status})
    outcomes[name] = (status, buffer.getvalue())


class Section(NamedTuple):
    """One gate section: its name in the log, the banner above it, the work, and any verdict line."""

    name: str
    banner: str
    run: Callable[[], int]
    after: Callable[[int], None] | None = None


def run_sections(sections: list[Section], quiet: bool = False) -> dict[str, str]:
    """Run the sections in table order, starting the expensive independent ones together.

    Each concurrent section writes into its own buffer, so the terminal still reads top to bottom. With
    `quiet`, every section's transcript is kept for the summary instead of printed as it arrives.
    """
    outcomes: dict[str, tuple[int, str]] = {}
    alongside = [section for section in sections if section.name in CONCURRENT]
    if len(alongside) > 1:
        stream = _ThreadStream(sys.stdout)
        with contextlib.redirect_stdout(stream):
            workers = [
                threading.Thread(target=run_alongside, args=(section.name, section.run, stream, outcomes))
                for section in alongside
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
    printed: dict[str, str] = {}
    for section in sections:
        if section.name in outcomes:
            status, output = outcomes[section.name]
        else:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                status = timed(section.name, section.run)
            output = buffer.getvalue()
            outcomes[section.name] = (status, output)
        if section.after is not None:
            extra = io.StringIO()
            with contextlib.redirect_stdout(extra):
                section.after(status)
            output += extra.getvalue()
            outcomes[section.name] = (status, output)
        printed[section.name] = output
        if not quiet:
            if section.banner:
                print(section.banner, flush=True)
            print(output, end="")
    return printed


def verdict_line(output: str) -> str:
    """The last line a section printed, without its tag: the tally a summary stands on."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("[OK]", "[FAIL]", "[WARN]", "[INFO]", "[SKIP]")) and "] " in stripped:
            return stripped.split("] ", 1)[1]
        return stripped
    return ""


def print_summary(printed: dict[str, str]) -> None:
    """One line per section: what it reported, how long it took, and the run's totals."""
    print("\n=== SUMMARY ===")
    print(f"{'result':<7}{'section':<22}{'time':>8}  reported")
    for item in TIMES:
        name = str(item["section"])
        result = "FAIL" if item["status"] else "ok"
        reporter = verdict_line(printed.get(name, ""))
        print(f"{result:<7}{name:<22}{float(str(item['seconds'])):>7.1f}s  {reporter[:96]}")
    failed = [str(item["section"]) for item in TIMES if item["status"]]
    spent = sum(float(str(item["seconds"])) for item in TIMES)
    print(f"{'total':<7}{len(TIMES)} section(s){spent:>9.1f}s  {len(failed)} failed")


def report_sections() -> int:
    """The exit code and the line that explains it: a failing run always names its sections.

    The code comes from the recorded sections and nothing else, so a nonzero exit cannot happen
    without a `[FAIL]` line beside it.
    """
    failed = [str(item["section"]) for item in TIMES if item["status"]]
    if not failed:
        print("[OK] every section passed")
        return 0
    print(f"[FAIL] {len(failed)} section(s) failed: {', '.join(failed)}")
    return 1


def run_and_report(sections: list[Section], summary: bool) -> dict[str, str]:
    """Run the sections and, when the run asked for it, print the one-line-per-section view."""
    printed = run_sections(sections, quiet=summary)
    if summary:
        print_summary(printed)
    return printed


def write_timings() -> Path:
    """One file per gate run under the prunable logs folder; a run's own sections sit inside it."""
    folder = project_cfg.SCRIPTS_DIR / "state" / "logs" / "shared" / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {
                "commit": (changes.git_text_or_none("rev-parse", "HEAD") or "").strip(),
                "dirty": bool(changed_since_upstream()),
                "total_seconds": round(time.perf_counter() - _started_at, 2),
                "work_seconds": round(sum(item["seconds"] for item in TIMES), 2),
                "sections": TIMES,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


PYTHON_SECTIONS = frozenset(
    {
        "annotations",
        "bare any",
        "line length",
        "lint",
        "types",
        "formatting",
        "comments",
        "dead code",
        "dynamic imports",
        "walrus",
        "expression",
        "network timeouts",
        "overlay access",
        "inventory",
    }
)
MARKDOWN_SECTIONS = frozenset({"typography", "spelling variants", "spelling"})
FRONTEND_SUFFIXES = frozenset({".js", ".css", ".html", ".cjs", ".ts"})
DEPENDENCY_FILES = ("pyproject.toml", "uv.lock")


def touched_sections(paths: list[str]) -> set[str]:
    """The sections whose inputs changed: a rename of batch files needs layout and docs only."""
    sections = {"layout", "docs", "single-owner tokens"}
    suffixes = {Path(path).suffix.lower() for path in paths}
    if ".py" in suffixes:
        sections |= PYTHON_SECTIONS
    if ".md" in suffixes:
        sections |= MARKDOWN_SECTIONS
    if suffixes & FRONTEND_SUFFIXES:
        sections.add("front-end wiring")
    if any(path.endswith(DEPENDENCY_FILES) for path in paths):
        sections |= {"advisories", "lock check", "deptry"}
    if any("config/models" in path or path.endswith("ids.py") for path in paths):
        sections.add("model references")
    return sections


def _flag(argv: list[str], name: str) -> bool:
    return name in argv


def touched_gate(argv: list[str] | None = None, changed: list[str] | None = None) -> int:
    """Run only the sections the change reaches, cheapest first."""
    argv = list(sys.argv[1:] if argv is None else argv)
    changed = changed_since_upstream() if changed is None else changed
    # - a rename leaves the old name in the change set, and a deleted file has nothing to read
    existing = [path for path in changed if (project_cfg.BASE_DIR / path).is_file()]
    python_files = [path for path in existing if path.endswith(".py")]
    selected = touched_sections(changed)
    print(f"=== TOUCHED: {', '.join(sorted(selected))} ===", flush=True)
    table = (
        ("layout", "=== LAYOUT ===", layout.main),
        ("single-owner tokens", "\n=== SINGLE-OWNER TOKENS ===", lambda: owned_tokens.main([])),
        ("docs", "\n=== DOCUMENTATION ===", lambda: docs.main([])),
        ("model references", "\n=== MODEL REFERENCE DRIFT ===", model_references.main),
        ("front-end wiring", "\n=== FRONT-END WIRING ===", frontend_wiring.main),
        ("network timeouts", "\n=== NETWORK TIMEOUTS ===", lambda: network_timeouts.main(python_files)),
        ("overlay access", "\n=== OVERLAY ACCESS ===", lambda: overlay_access.main(python_files)),
        ("lint", "\n=== LINT ===", lint_check),
        ("types", "", lambda: scoped_type_check(existing, _flag(argv, "--fast"))),
        ("formatting", "\n=== PYTHON FORMATTING ===", lambda: format_check(python_files)),
        ("inventory", "", lambda: inventory_check({}, _flag(argv, "--fast"), python_files)),
        ("typography", "\n=== TYPOGRAPHIC PUNCTUATION ===", lambda: typography.main(existing)),
        ("comments", "\n=== COMMENTS ===", lambda: comments.main(python_files)),
        ("annotations", "\n=== ANNOTATION COMPLEXITY ===", lambda: annotations.main(python_files)),
        ("line length", "\n=== LINE LENGTH ===", lambda: line_length.main(python_files)),
        ("bare any", "\n=== BARE ANY ===", lambda: bare_any.main(python_files)),
        ("dead code", "\n=== DEAD CODE ===", lambda: dead_code.scoped(python_files)),
        ("dynamic imports", "\n=== DYNAMIC IMPORTS ===", lambda: dynamic_imports.main(python_files)),
        ("walrus", "\n=== WALRUS OPERATOR ===", lambda: walrus.main(python_files)),
        ("expression", "\n=== EXPRESSION DEPTH ===", lambda: expression.main(python_files)),
        ("spelling variants", "\n=== AMERICAN SPELLING ===", lambda: spellings.main(existing)),
        ("spelling", "\n=== SPELLING ===", lambda: spelling_check(existing)),
        ("advisories", "", lambda: advisory_check(_flag(argv, "--fast"))),
        ("lock check", "\n=== DEPENDENCY HYGIENE ===", lock_check),
        ("deptry", "", declaration_check),
    )
    chosen = [Section(name, banner, function) for name, banner, function in table if name in selected]
    run_and_report(chosen, _flag(argv, "--summary"))
    slowest = sorted(TIMES, key=lambda item: float(str(item["seconds"])), reverse=True)[:3]
    summary = ", ".join(f"{item['section']} {item['seconds']}s" for item in slowest)
    print(f"\n[TIME] {write_timings()} (slowest: {summary})")
    _prune_after_run()
    return report_sections()


def _prune_after_run() -> None:
    """Keep every regenerable tree two deep, so the log this run wrote never becomes a backlog."""
    # - imported here because the pruners belong to the tools role, not to the gate

    for line in prune_generated(7, 30, 30, dry_run=False):
        print(f"[PRUNE] {line}")
    count, freed = cleanup.prune_outputs(dry_run=False)
    if count:
        print(f"[PRUNE] superseded run evidence: {count} item(s), {freed / 1e6:.1f} MB")
    expired = cleanup.prune_trash()
    if expired:
        print(f"[PRUNE] trash older than {cleanup.TRASH_DAYS} days: {expired} folder(s)")


def _package_summary(fast: bool) -> dict[str, int] | None:
    """Installed package counts, recorded as their own section; --fast skips the audit."""
    if fast:
        return None
    started = time.perf_counter()
    counts = package_audit.summary()
    TIMES.append({"section": "package summary", "seconds": round(time.perf_counter() - started, 2), "status": 0})
    return counts


def full_gate(argv: list[str] | None = None) -> int:
    """Run every section; --all and an empty change set both land here."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-format-check", action="store_true", help="skip the ruff format comparison")
    parser.add_argument("--tests", action="store_true", help="also run the model-free test suite")
    parser.add_argument("--summary", action="store_true", help="one line per section instead of the transcript")
    parser.add_argument("--prune", action="store_true", help="list installed packages nothing imports or declares")
    parser.add_argument("--remove", action="store_true", help="with --prune: uninstall those leftovers")
    parser.add_argument("--scrub", action="store_true", help="scan the tree and history for personal terms")
    parser.add_argument(
        "--fast", action="store_true", help="skip the type check, inventory and advisory feed; about five seconds"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="run every section; without it the gate runs only what changed, and an empty change set runs all",
    )
    args = parser.parse_args(argv)
    if args.prune:
        return package_audit.main(remove=args.remove)
    if args.scrub:
        return public_audit_main(["--scrub"])

    counts = _package_summary(args.fast)
    sections = [
        Section("layout", "=== LAYOUT ===", layout.main),
        Section("single-owner tokens", "\n=== SINGLE-OWNER TOKENS ===", lambda: owned_tokens.main([])),
        Section("docs", "\n=== DOCUMENTATION ===", lambda: docs.main([])),
        Section("model references", "\n=== MODEL REFERENCE DRIFT ===", model_references.main),
        Section("front-end wiring", "\n=== FRONT-END WIRING ===", frontend_wiring.main),
        Section("network timeouts", "\n=== NETWORK TIMEOUTS ===", lambda: network_timeouts.main([])),
        Section("overlay access", "\n=== OVERLAY ACCESS ===", lambda: overlay_access.main([])),
        Section(
            "lint",
            "\n=== LINT ===",
            lint_check,
            lambda status: print("[OK] Lint clean" if not status else "[FAIL] Lint findings above"),
        ),
        Section("types", "", lambda: type_check(args.fast)),
        Section("inventory", "", lambda: inventory_check(counts or {}, args.fast)),
    ]
    if not args.no_format_check:
        sections.append(
            Section(
                "formatting",
                "\n=== PYTHON FORMATTING ===",
                format_check,
                lambda status: print(
                    "[OK] Formatting matches" if not status else "[FAIL] Formatting differs; run review/format_py.bat"
                ),
            )
        )
    lock: dict[str, list[str]] = {}

    def run_lock() -> int:
        """The lock issues, kept for the verdict lines that print after deptry."""
        lock["issues"] = package_audit.lock_issues()
        return int(bool(lock["issues"]))

    def report_lock(_status: int) -> None:
        if counts:
            print(f"{counts['locked']} locked, {counts['installed']} installed, {counts['leftovers']} leftovers")

    def report_declaration(status: int) -> None:
        print("[OK] Imports match the pins" if not status else "[FAIL] deptry reported issues")
        for issue in lock["issues"][:10]:
            print(f"[FAIL] {issue}")
        print("[OK] uv.lock matches pyproject" if not lock["issues"] else f"[FAIL] {len(lock['issues'])} lock issue(s)")

    sections.extend(
        [
            Section("typography", "\n=== TYPOGRAPHIC PUNCTUATION ===", lambda: typography.main([])),
            Section("comments", "\n=== COMMENTS ===", lambda: comments.main([])),
            Section("annotations", "\n=== ANNOTATION COMPLEXITY ===", lambda: annotations.main([])),
            Section("line length", "\n=== LINE LENGTH ===", lambda: line_length.main([])),
            Section("bare any", "\n=== BARE ANY ===", lambda: bare_any.main([])),
            Section("dead code", "\n=== DEAD CODE ===", lambda: dead_code.main([])),
            Section("dynamic imports", "\n=== DYNAMIC IMPORTS ===", lambda: dynamic_imports.main([])),
            Section("walrus", "\n=== WALRUS OPERATOR ===", lambda: walrus.main([])),
            Section("expression", "\n=== EXPRESSION DEPTH ===", lambda: expression.main([])),
            Section("spelling variants", "\n=== AMERICAN SPELLING ===", lambda: spellings.main([])),
            Section(
                "spelling",
                "\n=== SPELLING ===",
                spelling_check,
                lambda status: print("[OK] Spelling clean" if not status else "[FAIL] Spelling findings above"),
            ),
            Section("advisories", "", lambda: advisory_check(args.fast)),
            Section("lock check", "\n=== DEPENDENCY HYGIENE ===", run_lock, report_lock),
            Section("deptry", "", declaration_check, report_declaration),
        ]
    )
    run_and_report(sections, args.summary)

    tests_status = 0
    if args.tests:
        print("\n=== TEST SUITE ===", flush=True)
        started = time.perf_counter()
        tests_status = subprocess.run(
            [str(project_cfg.VENV_DIR / "Scripts" / "python.exe"), "-m", "scripts.tests.run", "--all"],
            cwd=project_cfg.BASE_DIR,
            check=False,
        ).returncode
        TIMES.append(
            {"section": "test suite", "seconds": round(time.perf_counter() - started, 2), "status": tests_status}
        )

    slowest = sorted(TIMES, key=lambda item: float(str(item["seconds"])), reverse=True)[:3]
    summary = ", ".join(f"{item['section']} {item['seconds']}s" for item in slowest)
    print(f"\n[TIME] {write_timings()} (slowest: {summary})")
    return report_sections()


def main(argv: list[str] | None = None) -> int:
    """Scope the gate to the change by default; `--all`, `--prune`, `--scrub` or a clean tree run every section.

    `--commit` is the pre-commit stage, which judges what it is about to record: the working tree against
    `HEAD`, not the commits already made. `--push` is the pre-push stage: every section when the unpushed
    commits touch Python, and only the prose sections when they do not, since no Python behavior changed
    and the last push was green.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # - a run's status comes from its own sections, so no earlier run in this process can fail it
    global _started_at
    TIMES.clear()
    _started_at = time.perf_counter()
    pushing = _flag(argv, "--push")
    committing = _flag(argv, "--commit")
    argv = [argument for argument in argv if argument not in ("--push", "--commit")]
    baseline = True
    try:
        changed = changed_since_head() if committing else changed_since_upstream()
    except GitError as error:
        print(f"[FAIL] git could not report the change: {error}")
        return 1
    except NoUpstreamError:
        # Nothing to compare against, so no section can be narrowed on evidence; every one runs.
        baseline = False
        changed = []
        print("[GATE] this branch has no upstream ref; every section runs, and --fast skips the slow ones", flush=True)
    # - a clean tree is evidence that nothing needs checking, unless a flag asked for the whole gate
    forced = _flag(argv, "--all") or _flag(argv, "--prune") or _flag(argv, "--scrub")
    if not changed and not forced:
        if baseline:
            print("[GATE] nothing is uncommitted or unpushed; nothing to check, and --all runs every section")
            return 0
        return full_gate(argv)
    prose_only = pushing and not any(path.endswith(".py") for path in changed)
    if prose_only:
        print("[PUSH] no Python change since upstream; prose sections only", flush=True)
    if prose_only or (not pushing and not forced and changed):
        return touched_gate(argv, changed)
    return full_gate(argv)


if __name__ == "__main__":
    raise SystemExit(main())
