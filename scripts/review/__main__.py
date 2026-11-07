"""Run the repository structure, type and size/complexity reviews."""

import subprocess

from scripts.config import project_config as project_cfg
from scripts.review import audit, frontend, model_drift, structure


def main() -> int:
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
    audit_status = audit.main()
    return int(bool(structure_status or model_status or frontend_status or type_status or audit_status))


if __name__ == "__main__":
    raise SystemExit(main())
