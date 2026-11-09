"""Skip a live suite when the code it covers has not changed since its last pass.

The stamp is a content hash of the launcher, config, test and benchmark sources; documentation and
evidence changes do not invalidate it. Set `AI_LIVE_FORCE=1` to run anyway.
"""

import hashlib
import json
import os
import time

from scripts.config import project_config as project_cfg

INPUT_ROOTS = ("scripts/launchers", "scripts/config", "scripts/tests/cases", "scripts/benchmarks", "bat")
SUFFIXES = frozenset({".py", ".cjs", ".mjs", ".js", ".html", ".json", ".yaml", ".bat"})
SKIP_PARTS = frozenset({"__pycache__", "state", "output", "old", "retired"})


def fingerprint() -> str:
    digest = hashlib.sha256()
    for root in INPUT_ROOTS:
        base = project_cfg.BASE_DIR / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES or SKIP_PARTS & set(path.parts):
                continue
            digest.update(path.relative_to(project_cfg.BASE_DIR).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _stamps() -> dict[str, dict[str, str]]:
    path = project_cfg.STATE_DIR / "shared" / "live-stamps.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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
    return stamp is not None and stamp.get("fingerprint") == fingerprint()


def record(suite: str, targets: list[str]) -> None:
    stamps = _stamps()
    key = f"{suite}:{','.join(sorted(targets))}"
    stamps[key] = {"fingerprint": fingerprint(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(stamps)
