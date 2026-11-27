"""The overlay's private scan of the tracked tree: it owns the rules, this runs them.

The gate calls `run_private_audit` on every change; `python -m scripts.review --scrub` calls it with
`--scrub` before a publish. Nothing here names a category or a term, so the public tree does not say
what it screens. A machine with no overlay reports a skip rather than a pass.
"""

import os
import subprocess
import sys

from scripts.config import local_overlay
from scripts.config import project_config as project_cfg


def run_private_audit(arguments: list[str]) -> int:
    """Run the scan with these arguments; a missing overlay is a skip, never a pass."""
    script = local_overlay.private_audit_script()
    if not script.is_file():
        print("[SKIP] no private overlay on this machine, so nothing was screened")
        return 0
    inherited = os.environ.get("PYTHONPATH", "")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(project_cfg.BASE_DIR), *filter(None, [inherited])])}
    return subprocess.run(
        [sys.executable, str(script), *arguments], cwd=project_cfg.BASE_DIR, env=env, check=False
    ).returncode
