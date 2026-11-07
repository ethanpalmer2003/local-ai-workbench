"""Run the repository structure, type and size/complexity reviews."""

import argparse
import json
import subprocess

from scripts.config import project_config as project_cfg
from scripts.review import dependencies, frontend_wiring, inventory_code, model_references, structure_docs

SPELL_EXCLUDED = (
    "data/",
    "frameworks/",
    "trash/",
    "scripts/state/",
    "scripts/tests/output/",
    "scripts/benchmarks/output/",
)


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
    checker = project_cfg.SCRIPTS_DIR / ".venv/Scripts/codespell.exe"
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
    checker = project_cfg.SCRIPTS_DIR / ".venv/Scripts/pip-audit.exe"
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


def format_check() -> int:
    """Formatting is optional: the codebase keeps hand-wrapped lines ruff format would join."""
    checker = project_cfg.SCRIPTS_DIR / ".venv/Scripts/ruff.exe"
    return subprocess.run(
        [str(checker), "format", "--check", "--config", str(project_cfg.BASE_DIR / "pyproject.toml"), "."],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-format-check", action="store_true", help="skip the ruff format comparison")
    parser.add_argument("--prune", action="store_true", help="list installed packages outside the import graph")
    args = parser.parse_args(argv)
    if args.prune:
        return dependencies.main()

    print("=== STRUCTURE AND DOCUMENTATION ===", flush=True)
    structure_status = structure_docs.main()

    print("\n=== MODEL REFERENCE DRIFT ===", flush=True)
    model_status = model_references.main()

    print("\n=== FRONT-END WIRING ===", flush=True)
    frontend_status = frontend_wiring.main()

    print("\n=== TYPE CHECK ===", flush=True)
    checker = project_cfg.SCRIPTS_DIR / ".venv/Scripts/basedpyright.exe"
    try:
        type_status = subprocess.run(
            [str(checker), "--level", "error"], cwd=project_cfg.BASE_DIR, check=False
        ).returncode
    except OSError as error:
        print(f"[FAIL] Could not run basedpyright at {checker}: {error}")
        type_status = 1

    print("\n=== REPOSITORY INVENTORY AND PYTHON COMPLEXITY ===", flush=True)
    counts = dependencies.summary()
    inventory_status = inventory_code.main(counts)

    formatting_status = 0
    if not args.no_format_check:
        print("\n=== PYTHON FORMATTING ===", flush=True)
        formatting_status = format_check()
        print(
            "[OK] Formatting matches"
            if not formatting_status
            else "[WARN] Formatting differs; run review/format_py.bat"
        )

    print("\n=== SPELLING ===", flush=True)
    spelling_status = spelling_check()
    print("[OK] Spelling clean" if not spelling_status else "[FAIL] Spelling findings above")

    print("\n=== DEPENDENCY ADVISORIES ===", flush=True)
    audit_status, audit_note = security_audit()
    print(audit_note)

    print("\n=== DEPENDENCY HYGIENE ===", flush=True)
    drift = dependencies.drift_issues()
    print(f"{counts['pinned']} pinned, {counts['installed']} installed, {counts['unused']} unused")
    for issue in drift[:10]:
        print(f"[FAIL] {issue}")
    print("[OK] Requirements match the venv" if not drift else f"[FAIL] {len(drift)} drift entries")
    return int(
        bool(
            structure_status
            or model_status
            or frontend_status
            or type_status
            or inventory_status
            or formatting_status
            or spelling_status
            or audit_status
            or drift
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
