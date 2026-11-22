"""Skip a live suite when the code it covers has not changed since its last pass.

The stamp is a content hash of the launcher, config, test and benchmark sources; documentation and
evidence changes do not invalidate it. Set `AI_LIVE_FORCE=1` to run anyway.
"""

import json
import os
import time

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.shared import staleness

INPUT_ROOTS = ("scripts/launchers", "scripts/config", "scripts/tests/cases", "scripts/benchmarks", "bat")
SUFFIXES = frozenset({".py", ".cjs", ".mjs", ".js", ".html", ".json", ".yaml", ".bat"})
SKIP_PARTS = frozenset({"__pycache__", "state", "output", "old", "retired"})


def _installation_identity() -> bytes:
    """Installed models and frameworks: size and timestamp, never their bytes."""
    lines: list[str] = []
    for model in model_cfg.MODELS:
        try:
            stat = model.path.stat()
        except OSError:
            lines.append(f"{model.path}:missing")
            continue
        lines.append(f"{model.path}:{stat.st_size}:{stat.st_mtime_ns}")
    for component in project_cfg.COMPONENTS.values():
        root = component.framework_dir
        if not root.is_dir():
            continue
        try:
            lines.append(f"{root}:{root.stat().st_mtime_ns}")
        except OSError:
            continue
        for marker in (".last_update_hash", ".git/HEAD"):
            path = root / marker
            if path.is_file():
                lines.append(f"{path}:{path.read_text(encoding='utf-8', errors='ignore').strip()}")
    return "\n".join(lines).encode()


def fingerprint() -> str:
    """Digest of the sources a live suite covers, plus which models and frameworks are installed."""
    return staleness.tree_fingerprint(
        INPUT_ROOTS, project_cfg.BASE_DIR, SUFFIXES, SKIP_PARTS, extra=_installation_identity()
    )


def _stamps() -> dict[str, dict[str, str]]:
    path = project_cfg.STATE_DIR / "shared" / "live-stamps.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def _save(stamps: dict[str, dict[str, str]]) -> None:
    path = project_cfg.STATE_DIR / "shared" / "live-stamps.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamps, indent=2) + "\n", encoding="utf-8")


def forced() -> bool:
    return os.environ.get("AI_LIVE_FORCE") == "1"


def unchanged(suite: str, targets: list[str]) -> bool:
    """True when this target set passed under the current sources."""
    if forced():
        return False
    stamp = _stamps().get(f"{suite}:{','.join(sorted(targets))}")
    return staleness.matched((stamp or {}).get("fingerprint"), fingerprint())


def record(suite: str, targets: list[str]) -> None:
    stamps = _stamps()
    key = f"{suite}:{','.join(sorted(targets))}"
    stamps[key] = {"fingerprint": fingerprint(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(stamps)
