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
from scripts.review import (
    comments,
    docs,
    frontend_wiring,
    inventory_code,
    layout,
    model_references,
    network_timeouts,
    overlay_access,
    package_audit,
    spellings,
    typography,
)
from scripts.review.public_audit import main as public_audit_main

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


def spelling_check() -> int:
    checker = project_cfg.VENV_DIR / "Scripts" / "codespell.exe"
    targets = _spelling_targets()
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


def format_check() -> int:
    """Formatting is optional: the codebase keeps hand-wrapped lines ruff format would join."""
    checker = project_cfg.VENV_DIR / "Scripts" / "ruff.exe"
    return subprocess.run(
        [str(checker), "format", "--check", "--config", str(project_cfg.BASE_DIR / "pyproject.toml"), "."],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


def consents(given: bool) -> bool:
    """The gate is repo-wide, so it asks the person at the terminal; an unattended run must say --yes.
    - an agent or scheduled job has nobody to answer, so silence is a refusal, never consent
    """
    if given:
        return True
    if not sys.stdin.isatty():
        print(
            "[FAIL] The full review gate needs the user's agreement: a person must confirm it, "
            "or pass --yes when they asked for it.",
            flush=True,
        )
        return False
    answer = input("Run the full review gate (repo-wide, no models)? Type yes to continue: ").strip().lower()
    return answer == "yes"


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


def inventory_check(counts: dict[str, int], fast: bool) -> int:
    """Folder and function inventory; it writes a report, so --fast skips it."""
    if fast:
        return 0
    print("\n=== REPOSITORY INVENTORY ===", flush=True)
    return inventory_code.main(counts)


def advisory_check(fast: bool) -> int:
    """Installed-package advisories; the only section that needs the network, so --fast skips it."""
    if fast:
        print("\n=== DEPENDENCY ADVISORIES ===\n[SKIP] --fast")
        return 0
    print("\n=== DEPENDENCY ADVISORIES ===", flush=True)
    status, note = security_audit()
    print(note)
    return status


def timed[T](name: str, function: Callable[..., T], *args: Any) -> T:
    """Run one gate section and keep its duration, so history answers cost questions without a rerun."""
    started = time.perf_counter()
    status = function(*args)
    TIMES.append({"section": name, "seconds": round(time.perf_counter() - started, 2), "status": status})
    return status


def write_timings() -> Path:
    """One file per gate run under the prunable logs folder; a run's own sections sit inside it."""
    folder = project_cfg.SCRIPTS_DIR / "state" / "logs" / "shared" / "review"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}.json"
    path.write_text(
        json.dumps({"total_seconds": round(sum(item["seconds"] for item in TIMES), 2), "sections": TIMES}, indent=1),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-format-check", action="store_true", help="skip the ruff format comparison")
    parser.add_argument("--tests", action="store_true", help="also run the model-free test suite")
    parser.add_argument("--prune", action="store_true", help="list installed packages nothing imports or declares")
    parser.add_argument("--remove", action="store_true", help="with --prune: uninstall those leftovers")
    parser.add_argument("--scrub", action="store_true", help="scan the tree and history for personal terms")
    parser.add_argument("--yes", action="store_true", help="confirm the full gate; otherwise a person is asked")
    parser.add_argument(
        "--fast", action="store_true", help="skip the type check, inventory and advisory feed; about five seconds"
    )
    args = parser.parse_args(argv)
    if args.prune:
        return package_audit.main(remove=args.remove)
    if args.scrub:
        return public_audit_main(["--scrub"])
    if not consents(args.yes):
        return 1

    print("=== LAYOUT ===", flush=True)
    layout_status = timed("layout", layout.main)

    print("\n=== DOCUMENTATION ===", flush=True)
    docs_status = timed("docs", docs.main, [])

    print("\n=== MODEL REFERENCE DRIFT ===", flush=True)
    model_status = timed("model references", model_references.main)

    print("\n=== FRONT-END WIRING ===", flush=True)
    frontend_status = timed("front-end wiring", frontend_wiring.main)

    print("\n=== NETWORK TIMEOUTS ===", flush=True)
    timeout_status = timed("network timeouts", network_timeouts.main, [])

    print("\n=== OVERLAY ACCESS ===", flush=True)
    overlay_status = timed("overlay access", overlay_access.main, [])

    print("\n=== LINT ===", flush=True)
    lint_status = timed("lint", lint_check)
    print("[OK] Lint clean" if not lint_status else "[FAIL] Lint findings above")

    type_status = timed("types", type_check, args.fast)
    counts = None
    if not args.fast:
        started_summary = time.perf_counter()
        counts = package_audit.summary()
        TIMES.append(
            {"section": "package summary", "seconds": round(time.perf_counter() - started_summary, 2), "status": 0}
        )
    inventory_status = timed("inventory", inventory_check, counts or {}, args.fast)

    formatting_status = 0
    if not args.no_format_check:
        print("\n=== PYTHON FORMATTING ===", flush=True)
        formatting_status = timed("formatting", format_check)
        print(
            "[OK] Formatting matches"
            if not formatting_status
            else "[WARN] Formatting differs; run review/format_py.bat"
        )

    print("\n=== TYPOGRAPHIC PUNCTUATION ===", flush=True)
    dash_status = timed("typography", typography.main, [])

    print("\n=== COMMENTS ===", flush=True)
    comment_status = timed("comments", comments.main, [])

    print("\n=== AMERICAN SPELLING ===", flush=True)
    variant_status = timed("spelling variants", spellings.main, [])

    print("\n=== SPELLING ===", flush=True)
    spelling_status = timed("spelling", spelling_check)
    print("[OK] Spelling clean" if not spelling_status else "[FAIL] Spelling findings above")

    audit_status = timed("advisories", advisory_check, args.fast)

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
            [str(project_cfg.VENV_DIR / "Scripts" / "python.exe"), "-m", "scripts.tests.run"],
            cwd=project_cfg.BASE_DIR,
            check=False,
        ).returncode
        TIMES.append(
            {"section": "test suite", "seconds": round(time.perf_counter() - started, 2), "status": tests_status}
        )

    slowest = sorted(TIMES, key=lambda item: float(str(item["seconds"])), reverse=True)[:3]
    summary = ", ".join(f"{item['section']} {item['seconds']}s" for item in slowest)
    print(f"\n[TIME] {write_timings()} (slowest: {summary})")
    return int(
        bool(
            layout_status
            or docs_status
            or model_status
            or frontend_status
            or timeout_status
            or overlay_status
            or lint_status
            or type_status
            or inventory_status
            or dash_status
            or comment_status
            or variant_status
            or formatting_status
            or spelling_status
            or audit_status
            or issues
            or declaration_status
            or tests_status
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
