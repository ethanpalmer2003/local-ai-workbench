"""Dead definitions and unreachable blocks, detected by vulture under this repository's policy.

Vulture owns detection. This module owns what counts as a finding, because its raw output on this
tree is 182 lines and almost none of them can be deleted:

- `unused method` and `unused attribute` are read outside the scan. `http.server` calls
  `close_connection` and `daemon_threads`, Win32 reads `LimitFlags`, and the speech servers read
  `length_scale` and `noise_scale` from a JSON body, so none of those names appears in a call this
  scan can see.
- `unused variable` is either an exported catalog constant (`config/models/ids.py`), which its
  importer names, or a local, which ruff already owns as F841.
- An `unused function` or `unused class` has no reader anywhere, and deleting it is the action this
  section exists to prompt. Unreachable blocks keep vulture's own full-confidence report.

The retired TTS pipeline stays out of the report until the removal decision in notes/TODO.md
lands: it is dead by design, and reporting it every run teaches the reader to skip the section.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import maintained_files

# - retired code awaiting a removal decision; the entry in notes/TODO.md owns that decision
RETIRED = {"scripts/launchers/audiocpp/tts_legacy_buffered.py"}
MIN_CONFIDENCE = "60"
ACTIONABLE = re.compile(r": (?:unused (?:function|class)|unreachable code)\b")
LOCATION = re.compile(r"^(?P<name>.*?):(?P<line>\d+): ")


def relative(line: str) -> str:
    """Repo-relative posix path of the file a vulture line names, however vulture wrote it."""
    match = LOCATION.match(line)
    name = match.group("name") if match else line.split(":", 1)[0]
    path = Path(name)
    if path.is_absolute():
        try:
            return path.relative_to(project_cfg.BASE_DIR).as_posix()
        except ValueError:
            return path.as_posix()
    return Path(name.replace("\\", "/")).as_posix()


def findings(output: str) -> list[str]:
    """Vulture findings whose name has no reader anywhere, or whose block no path reaches."""
    kept = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or not ACTIONABLE.search(line):
            continue
        if relative(line) in RETIRED:
            continue
        kept.append(line)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to scan (default: every maintained Python file)")
    args = parser.parse_args(argv)
    paths = [Path(item) for item in args.paths] or [path for path in maintained_files() if path.suffix == ".py"]
    result = subprocess.run(
        [sys.executable, "-m", "vulture", *(str(path) for path in paths), "--min-confidence", MIN_CONFIDENCE],
        cwd=project_cfg.BASE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    # - vulture: 0 nothing found, 3 dead code found, 1 invalid input, 2 bad arguments
    if result.returncode not in (0, 3):
        print(f"[FAIL] vulture could not scan: {(result.stderr or '').strip()[:400] or result.returncode}")
        return 1
    found = findings(result.stdout or "")
    for line in found[:MAX_REPORTED]:
        print(f"[FAIL] {line}")
    if not found:
        print(f"[OK] Dead code: {len(paths)} files, nothing unreferenced")
        return 0
    print(f"[FAIL] Dead code: {len(found)} finding(s); a definition with no reader is safe to delete")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
