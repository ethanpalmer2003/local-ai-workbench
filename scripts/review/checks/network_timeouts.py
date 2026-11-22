"""Every outbound HTTP call carries an explicit timeout.

A request without one waits for the peer forever: a stopped service, a half-open socket or a
proxy that never answers turns a bug into a hung run. The scan parses the source, so a call is
judged by its real keyword arguments: a URL or header mentioning "timeout" is not a bound, and
`timeout=None` is the same defect as spelling none. Socket probes that already call `settimeout`
are not HTTP calls and stay out of scope. Raw `http.client` connections count too: without
`timeout=` the connect and every later read wait forever, which is the same defect in a different
wrapper.
"""

import ast
import re
from pathlib import Path

from scripts.review import MAX_REPORTED
from scripts.review.lists.sources import check_targets
from scripts.shared.paths import display_path

LOCAL_REQUESTS = re.compile(r"^from scripts\.[\w.]* import requests\b", re.MULTILINE)
REQUESTS_CALLS = frozenset({"get", "post", "put", "patch", "delete", "head", "request"})
CONNECTION_CALLS = frozenset({"HTTPConnection", "HTTPSConnection"})


def _call_name(node: ast.Call) -> str:
    """The dotted name a call uses, or empty when its target is not a plain name or attribute chain.

    `requests.get(url, timeout=5).json().get("x")` is a dict read at the end of a chained expression,
    not a second HTTP call, so a target containing a call ends the name.
    """
    current: ast.expr = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


def _is_http_call(name: str, local_wrapper: bool) -> bool:
    if name == "urlopen" or name.endswith(".urlopen"):
        return True
    if name.split(".")[-1] in CONNECTION_CALLS:
        return True
    if name.startswith("httpx."):
        return True
    if local_wrapper:
        return False
    return name.startswith("requests.") and name.split(".")[-1] in REQUESTS_CALLS


def _unbounded_reason(node: ast.Call, local_wrapper: bool) -> str | None:
    """Why this call has no usable bound, or None when its timeout argument is real."""
    if not _is_http_call(_call_name(node), local_wrapper):
        return None
    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
    if "timeout" not in keywords:
        return "HTTP call without a timeout"
    value = keywords["timeout"]
    # - `timeout=None` waits forever, which is the defect this check exists for
    if isinstance(value, ast.Constant) and value.value is None:
        return "HTTP call with timeout=None"
    return None


def issues(path: Path) -> list[str]:
    """Call sites in one file that would wait without a bound."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    local_wrapper = bool(LOCAL_REQUESTS.search(text))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        reason = _unbounded_reason(node, local_wrapper)
        if reason is not None:
            found.append(f"{display_path(path)}:{node.lineno}: {reason}")
    return sorted(found, key=lambda issue: int(issue.rsplit(":", 2)[-2]))


def main(argv: list[str] | None = None) -> int:
    files = [path for path in check_targets(argv, (".py",)) if "tests" not in path.parts]
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
