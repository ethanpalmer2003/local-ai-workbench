"""Run the repository structure, type and size/complexity reviews."""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from scripts.shared import changes
from scripts.shared.changes import changed_paths
from scripts.shared.import_graph import (
    REACH_DEPTH,
    import_graph,
    module_files,
    module_name,
    module_paths,
    reverse_closure,
)

SPELL_EXCLUDED = (
    "data/",
    "frameworks/",
    "trash/",
    "scripts/state/",
    "scripts/tests/output/",
    "scripts/benchmarks/output/",
)
TIMES: list[dict[str, Any]] = []


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
    targets = list(paths) if paths else _spelling_targets()
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
        return subprocess.run([str(checker), "--level", "error"], cwd=project_cfg.BASE_DIR, check=False).returncode
    except OSError as error:
        print(f"[FAIL] Could not run basedpyright at {checker}: {error}")
        return 1


def scoped_type_check(paths: list[str], fast: bool) -> int:
    """basedpyright on what the change reaches: its modules and their direct importers.

    Anything further away cannot have been broken by this change, and the full project runs at push.
    A reach covering most of the tree costs less as one whole-project run, so it falls back to that.
    """
    if fast:
        print("\n=== TYPE CHECK ===\n[SKIP] --fast")
        return 0
    print("\n=== TYPE CHECK ===", flush=True)
    names = (module_name(path) for path in paths)
    modules = {name for name in names if name}
    known = module_files()
    if not modules:
        return 0
    reachable = reverse_closure(import_graph(), modules, depth=REACH_DEPTH)
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


def timed[T](name: str, function: Callable[..., T], *args: object) -> T:
    """Run one gate section and keep its duration, so history answers cost questions without a rerun."""
    started = time.perf_counter()
    status = function(*args)
    TIMES.append({"section": name, "seconds": round(time.perf_counter() - started, 2), "status": status})
    return status


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


def write_timings() -> Path:
    """One file per gate run under the prunable logs folder; a run's own sections sit inside it."""
    folder = project_cfg.SCRIPTS_DIR / "state" / "logs" / "shared" / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps(
            {
                "commit": changes.git("rev-parse", "HEAD").strip(),
                "dirty": bool(changed_paths()),
                "total_seconds": round(sum(item["seconds"] for item in TIMES), 2),
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


def touched_gate(argv: list[str] | None = None) -> int:
    """Run only the sections the working tree changed since upstream, cheapest first."""
    argv = list(sys.argv[1:] if argv is None else argv)
    changed = changed_paths()
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
        ("inventory", "", lambda: inventory_check(package_audit.summary(), _flag(argv, "--fast"), python_files)),
        ("typography", "\n=== TYPOGRAPHIC PUNCTUATION ===", lambda: typography.main(existing)),
        ("comments", "\n=== COMMENTS ===", lambda: comments.main(python_files)),
        ("annotations", "\n=== ANNOTATION COMPLEXITY ===", lambda: annotations.main(python_files)),
        ("line length", "\n=== LINE LENGTH ===", lambda: line_length.main(python_files)),
        ("bare any", "\n=== BARE ANY ===", lambda: bare_any.main(python_files)),
        ("dead code", "\n=== DEAD CODE ===", lambda: dead_code.main([])),
        ("dynamic imports", "\n=== DYNAMIC IMPORTS ===", lambda: dynamic_imports.main(python_files)),
        ("walrus", "\n=== WALRUS OPERATOR ===", lambda: walrus.main(python_files)),
        ("spelling variants", "\n=== AMERICAN SPELLING ===", lambda: spellings.main(existing)),
        ("spelling", "\n=== SPELLING ===", lambda: spelling_check(existing)),
        ("advisories", "", lambda: advisory_check(_flag(argv, "--fast"))),
        ("lock check", "\n=== DEPENDENCY HYGIENE ===", package_audit.lock_issues),
        ("deptry", "", declaration_check),
    )
    for name, banner, function in table:
        if name not in selected:
            continue
        if banner:
            print(banner, flush=True)
        timed(name, function)
    slowest = sorted(TIMES, key=lambda item: float(str(item["seconds"])), reverse=True)[:3]
    summary = ", ".join(f"{item['section']} {item['seconds']}s" for item in slowest)
    print(f"\n[TIME] {write_timings()} (slowest: {summary})")
    return report_sections()


def full_gate(argv: list[str] | None = None) -> int:
    """Run every section; --all and an empty change set both land here."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-format-check", action="store_true", help="skip the ruff format comparison")
    parser.add_argument("--tests", action="store_true", help="also run the model-free test suite")
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

    print("=== LAYOUT ===", flush=True)
    timed("layout", layout.main)

    print("\n=== SINGLE-OWNER TOKENS ===", flush=True)
    timed("single-owner tokens", owned_tokens.main, [])

    print("\n=== DOCUMENTATION ===", flush=True)
    timed("docs", docs.main, [])

    print("\n=== MODEL REFERENCE DRIFT ===", flush=True)
    timed("model references", model_references.main)

    print("\n=== FRONT-END WIRING ===", flush=True)
    timed("front-end wiring", frontend_wiring.main)

    print("\n=== NETWORK TIMEOUTS ===", flush=True)
    timed("network timeouts", network_timeouts.main, [])

    print("\n=== OVERLAY ACCESS ===", flush=True)
    timed("overlay access", overlay_access.main, [])

    print("\n=== LINT ===", flush=True)
    lint_status = timed("lint", lint_check)
    print("[OK] Lint clean" if not lint_status else "[FAIL] Lint findings above")

    timed("types", type_check, args.fast)
    counts = None
    if not args.fast:
        started_summary = time.perf_counter()
        counts = package_audit.summary()
        TIMES.append(
            {"section": "package summary", "seconds": round(time.perf_counter() - started_summary, 2), "status": 0}
        )
    timed("inventory", inventory_check, counts or {}, args.fast)

    formatting_status = 0
    if not args.no_format_check:
        print("\n=== PYTHON FORMATTING ===", flush=True)
        formatting_status = timed("formatting", format_check)
        print(
            "[OK] Formatting matches"
            if not formatting_status
            else "[FAIL] Formatting differs; run review/format_py.bat"
        )

    print("\n=== TYPOGRAPHIC PUNCTUATION ===", flush=True)
    timed("typography", typography.main, [])

    print("\n=== COMMENTS ===", flush=True)
    timed("comments", comments.main, [])

    print("\n=== ANNOTATION COMPLEXITY ===", flush=True)
    timed("annotations", annotations.main, [])

    print("\n=== LINE LENGTH ===", flush=True)
    timed("line length", line_length.main, [])

    print("\n=== BARE ANY ===", flush=True)
    timed("bare any", bare_any.main, [])

    print("\n=== DEAD CODE ===", flush=True)
    timed("dead code", dead_code.main, [])

    print("\n=== DYNAMIC IMPORTS ===", flush=True)
    timed("dynamic imports", dynamic_imports.main, [])

    print("\n=== WALRUS OPERATOR ===", flush=True)
    timed("walrus", walrus.main, [])

    print("\n=== AMERICAN SPELLING ===", flush=True)
    timed("spelling variants", spellings.main, [])

    print("\n=== SPELLING ===", flush=True)
    spelling_status = timed("spelling", spelling_check)
    print("[OK] Spelling clean" if not spelling_status else "[FAIL] Spelling findings above")

    timed("advisories", advisory_check, args.fast)

    print("\n=== DEPENDENCY HYGIENE ===", flush=True)
    issues = timed("lock check", package_audit.lock_issues)
    if counts:
        print(f"{counts['locked']} locked, {counts['installed']} installed, {counts['leftovers']} leftovers")
    declaration_status = timed("deptry", declaration_check)
    print("[OK] Imports match the pins" if not declaration_status else "[FAIL] deptry reported issues")
    for issue in issues[:10]:
        print(f"[FAIL] {issue}")
    print("[OK] uv.lock matches pyproject" if not issues else f"[FAIL] {len(issues)} lock issue(s)")

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

    `--push` is the pre-push stage: every section when the unpushed commits touch Python, and only the
    prose sections when they do not, since no Python behavior changed and the last push was green.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # - a run's status comes from its own sections, so no earlier run in this process can fail it
    TIMES.clear()
    pushing = _flag(argv, "--push")
    argv = [argument for argument in argv if argument != "--push"]
    changed = changed_paths()
    prose_only = pushing and not any(path.endswith(".py") for path in changed)
    if prose_only:
        print("[PUSH] no Python change since upstream; prose sections only", flush=True)
    if prose_only or (
        not pushing and not (_flag(argv, "--all") or _flag(argv, "--prune") or _flag(argv, "--scrub")) and changed
    ):
        return touched_gate(argv)
    return full_gate(argv)


if __name__ == "__main__":
    raise SystemExit(main())
