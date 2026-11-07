"""Run the repository structure, type and size/complexity reviews."""

import argparse
import subprocess

from scripts.config import project_config as project_cfg
from scripts.review import frontend, inventory, model_drift, structure


def format_check() -> int:
    """Formatting is optional: the codebase keeps hand-wrapped lines ruff format would join."""
    checker = project_cfg.SCRIPTS_DIR / ".venv/Scripts/ruff.exe"
    return subprocess.run(
        [str(checker), "format", "--check", "--config", str(project_cfg.BASE_DIR / "pyproject.toml"), "scripts"],
        cwd=project_cfg.BASE_DIR,
        check=False,
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-format-check", action="store_true", help="skip the ruff format comparison")
    args = parser.parse_args(argv)

    print("=== STRUCTURE AND DOCUMENTATION ===", flush=True)
    structure_status = structure.main()

    print("\n=== MODEL REFERENCE DRIFT ===", flush=True)
    model_status = model_drift.main()

    print("\n=== FRONT-END WIRING ===", flush=True)
    frontend_status = frontend.main()

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
    inventory_status = inventory.main()

    formatting_status = 0
    if not args.no_format_check:
        print("\n=== PYTHON FORMATTING ===", flush=True)
        formatting_status = format_check()
        print(
            "[OK] Formatting matches" if not formatting_status else "[WARN] Formatting differs; run review/format.bat"
        )
    return int(
        bool(
            structure_status or model_status or frontend_status or type_status or inventory_status or formatting_status
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
