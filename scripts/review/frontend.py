"""Check front-end wiring: HTML/JS asset paths, DOM ids and launcher settings keys.

Static and literal-only: paths composed of `__dirname` (or a base variable derived from it)
plus string literals, and loop variables bound to a literal array, are resolved and must exist.
Computed or templated paths are skipped rather than guessed.
"""

import os
import re
from pathlib import Path

from scripts.config import project_config as project_cfg

EXCLUDED = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "state",
    "output",
    "old",
    "retired",
    "comfyui-archive",
    "frameworks",
    "data",
    "trash",
}
SUFFIXES = (".js", ".cjs", ".html")
MAX_REPORTED = 40

SCRIPT_ATTR = re.compile(r"<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.I)
INLINE_SCRIPT = re.compile(r"<script>([\s\S]*?)</script>", re.I)
HTML_ID = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']")
DOM_REF = re.compile(r"getElementById\(\s*[\"']([^\"']+)[\"']|querySelector\(\s*[\"']#([\w-]+)")
BASE_ASSIGN = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*path\.(?:join|resolve)\(\s*(__dirname|\w+)\s*"
    r"((?:\s*,\s*[\"'][^\"']*[\"'])*)\s*\)"
)
PATH_CALL = re.compile(r"path\.(?:join|resolve)\(([^()]*)\)")
FOR_LOOP = re.compile(r"for\s*\(\s*const\s+(\w+)\s+of\s*\[([^\]]*)\]\s*\)")
STRING = re.compile(r"[\"']([^\"']*)[\"']")
SETTINGS_READ = re.compile(r"\bsettings\.(\w+)")
SETTINGS_OPTIONAL = re.compile(r"\bsettings\.(\w+)\s*(?:\|\||\?\?)")

# Each entry pairs a launcher that injects `window.<object>` with the scripts that read it and
# the test fixture that must stand in for it. Add a row per injected settings object.
SETTINGS_CONTRACTS = (
    (
        "scripts/launchers/koboldcpp/kobold_lite.py",
        "koboldAudioSettings",
        (
            "scripts/launchers/koboldcpp/kobold_streaming.js",
            "scripts/launchers/koboldcpp/kobold_audio.js",
        ),
        "scripts/tests/cases/koboldcpp/kobold_streaming.cjs",
    ),
)


def _relative(path: Path) -> str:
    try:
        return path.relative_to(project_cfg.BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def frontend_files() -> list[Path]:
    files = []
    pending = [project_cfg.SCRIPTS_DIR]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path.is_junction() or path.is_symlink():
                continue
            if path.is_dir() and path.name not in EXCLUDED:
                pending.append(path)
            elif path.is_file() and path.suffix in SUFFIXES:
                files.append(path)
    return sorted(files)


def _join(base: Path, segments: list[str]) -> Path:
    value = str(base)
    for segment in segments:
        value = os.path.normpath(os.path.join(value, segment))
    return Path(value)


def _bases(text: str, directory: Path) -> dict[str, Path]:
    bases: dict[str, Path] = {"__dirname": directory}
    changed = True
    while changed:
        changed = False
        for match in BASE_ASSIGN.finditer(text):
            name, source, rest = match.groups()
            if name in bases or source not in bases:
                continue
            bases[name] = _join(bases[source], STRING.findall(rest))
            changed = True
    return bases


def _loop_variables(text: str) -> dict[str, list[str]]:
    return {match.group(1): STRING.findall(match.group(2)) for match in FOR_LOOP.finditer(text)}


def path_candidates(text: str, directory: Path) -> list[Path]:
    bases, loops = _bases(text, directory), _loop_variables(text)
    candidates = []
    for match in PATH_CALL.finditer(text):
        parts = [part.strip() for part in match.group(1).split(",")]
        if not parts:
            continue
        base = bases.get(parts[0])
        if base is None:
            continue
        expansions: list[list[str]] | None = [[]]
        for part in parts[1:]:
            if not part:
                continue
            literals = STRING.findall(part)
            if not literals:
                if part not in loops:
                    expansions = None
                    break
                literals = loops[part]
            expansions = [prefix + [literal] for prefix in (expansions or []) for literal in literals]
        if expansions is None:
            continue
        candidates += [_join(base, segments) for segments in expansions]
    return candidates


def _html_target_resolves(path: Path, target: str) -> bool:
    # The page is served at a shallow URL (/test/, /practice/), so its relative references are
    # resolved by the proxy, not next to the file. Accept a file-relative hit, or the same path
    # once its leading "../" segments (clamped at the server root) are stripped.
    if _join(path.parent, [target.replace("/", os.sep)]).is_file():
        return True
    rest = target
    while rest.startswith("../"):
        rest = rest[3:]
    for root in (project_cfg.BASE_DIR, project_cfg.SCRIPTS_DIR):
        if (root / rest).is_file():
            return True
    return False


def _html_asset_issues(path: Path, text: str) -> list[str]:
    issues = []
    for match in SCRIPT_ATTR.finditer(text):
        target = match.group(1)
        if target.startswith(("http:", "https:", "//", "/", "#", "data:")) or "${" in target or "{{" in target:
            continue
        if not _html_target_resolves(path, target):
            issues.append(f"{_relative(path)}: missing asset {target}")
    return issues


def path_issues() -> list[str]:
    issues = []
    for path in frontend_files():
        text = _read(path)
        if path.suffix == ".html":
            issues += _html_asset_issues(path, text)
            continue
        for candidate in path_candidates(text, path.parent):
            if not candidate.exists():
                issues.append(f"{_relative(path)}: missing asset {_relative(candidate)}")
    return issues


def dom_id_issues() -> list[str]:
    issues = []
    for path in frontend_files():
        if path.suffix != ".html":
            continue
        text = _read(path)
        defined = set(HTML_ID.findall(text))
        for block in INLINE_SCRIPT.findall(text):
            for name, selector in DOM_REF.findall(block):
                reference = name or selector
                if reference and reference not in defined:
                    issues.append(f"{_relative(path)}: unknown element id '{reference}'")
    return issues


def _emitted_keys(launcher: str) -> set[str]:
    text = _read(project_cfg.BASE_DIR / launcher)
    block = re.search(r"json\.dumps\(\s*\{(.*?)\}\s*\)", text, re.S)
    body = block.group(1) if block else ""
    keys = set(re.findall(r"[\"'](\w+)[\"']\s*:", body))
    if "streaming_defaults" in body:
        from scripts.launchers import launcher_config as cfg
        from scripts.launchers.audiocpp import audiocpp_catalog

        keys |= set(audiocpp_catalog.streaming_defaults(cfg.AUDIOCPP_SERVICE))
    return keys


def _fixture_keys(path: Path, name: str) -> set[str]:
    text = _read(path)
    keys = set()
    block = re.search(rf"{name}\s*:\s*\{{([^}}]*)\}}", text)
    if block:
        keys |= set(re.findall(r"(\w+)\s*:", block.group(1)))
    keys |= set(re.findall(rf"{name}\.(\w+)\s*=", text))
    return keys


def settings_issues() -> list[str]:
    issues = []
    for launcher, name, readers, fixture_path in SETTINGS_CONTRACTS:
        reads: set[str] = set()
        optional: set[str] = set()
        for relative in readers:
            text = _read(project_cfg.BASE_DIR / relative)
            reads |= set(SETTINGS_READ.findall(text))
            optional |= set(SETTINGS_OPTIONAL.findall(text))
        for key in sorted(reads - _emitted_keys(launcher)):
            issues.append(f"{launcher}: '{name}.{key}' is read but never emitted")
        fixture = project_cfg.BASE_DIR / fixture_path
        for key in sorted((reads - optional) - _fixture_keys(fixture, name)):
            issues.append(f"{_relative(fixture)}: '{name}.{key}' is read by the script but not provided")
    return issues


def main() -> int:
    issues = path_issues() + dom_id_issues() + settings_issues()
    for issue in issues[:MAX_REPORTED]:
        print(f"[FAIL] {issue}")
    if len(issues) > MAX_REPORTED:
        print(f"[WARN] {len(issues) - MAX_REPORTED} further issues; output bounded at {MAX_REPORTED}")
    print(f"[{'FAIL' if issues else 'OK'}] Front-end wiring: {len(frontend_files())} files, {len(issues)} issues")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
