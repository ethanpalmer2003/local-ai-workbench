"""Every outbound HTTP call carries an explicit timeout.

A request without one waits for the peer forever: a stopped service, a half-open socket or a
proxy that never answers turns a bug into a hung run. The scan is source-level, so it needs no
network and cannot be slow. Socket probes that already call `settimeout` are not HTTP calls and
stay out of scope. Raw `http.client` connections count too: without `timeout=` the connect and
every later read wait forever, which is the same defect in a different wrapper.
"""

import re
from pathlib import Path

from scripts.review import MAX_REPORTED
from scripts.review.sources import maintained_files

CALL = re.compile(
    r"(?:urllib\.request\.)?urlopen\("
    r"|requests\.(?:get|post|put|patch|delete|head|request)\("
    r"|httpx\."
    r"|(?:http\.client\.)?HTTPS?Connection\("
)
LOCAL_REQUESTS = re.compile(r"^from scripts\.[\w.]* import requests\b", re.MULTILINE)


def _span(text: str, start: int) -> str:
    """The text from an opening parenthesis to its match, so a wrapped call still counts."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def issues(path: Path) -> list[str]:
    """Call sites in one file that would wait without a bound."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    local_wrapper = bool(LOCAL_REQUESTS.search(text))
    found = []
    for match in CALL.finditer(text):
        if local_wrapper and match.group().startswith("requests."):
            continue
        call = _span(text, match.end() - 1)
        if "timeout" in call:
            continue
        line = text.count("\n", 0, match.start()) + 1
        found.append(f"{path.name}:{line}: HTTP call without a timeout")
    return found


def main(argv: list[str] | None = None) -> int:
    _ = argv
    files = [path for path in maintained_files() if path.suffix == ".py" and "tests" not in path.parts]
    found = [issue for path in files for issue in issues(path)]
    if not found:
        print(f"[OK] Network timeouts: {len(files)} files, 0 issues")
        return 0
    for issue in found[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    print(f"[FAIL] Network timeouts: {len(found)} issue(s); pass timeout= to each HTTP call")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
