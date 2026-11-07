"""Check the tracked tree for content that should not ship in a public repo.

- Reports only; exits 1 when anything is found, so it can gate a release
- Categories: secrets, personal home paths, machine paths in native configs,
  private vocabulary, character/voice inputs, large files, tracked ignored paths
- Allow-list entries state why a hit is expected; keep it short and specific
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.config import inputs
from scripts.config import project_config as project_cfg

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".bat",
    ".cjs",
    ".js",
    ".ts",
    ".ini",
    ".kcpps",
    ".txt",
    ".jinja",
    ".toml",
    ".ps1",
    ".cfg",
}
DOC_SUFFIXES = {".md"}
CONFIG_PREFIX = "scripts/config/"
IGNORED_ROOTS = {"data", "frameworks", "trash", "scripts/benchmarks/output", "scripts/tests/output"}
LARGE_FILE_BYTES = 500_000
MIN_VOICE_ID = 4

SECRETS = re.compile(r"github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}")
# - values under these keys are credentials even when they match no token prefix
CREDENTIALS = re.compile(
    r'"(?:password|passwd|adminpassword|api_?key|secret|token|access_token|auth_token)"\s*:\s*"([^"]+)"', re.I
)
HOME_PATHS = re.compile(r"C:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+")
MACHINE_PATHS = re.compile(r"C:[\\/]+AI[\\/]+")
PRIVATE_WORDS = re.compile(r"character|zzfixture|zzfixture|zzfixture|zzfixture", re.I)

# - prefix -> why the hit is expected; keep this list short and specific
ALLOWLIST = {
    "scripts/config/llamacpp/hrx-patches/": "recorded paths from a completed build run; evidence, not live config",
}

# - the audit and its fixtures hold every pattern by construction
SELF_REFERENTIAL = {"scripts/review/public_audit.py", "scripts/tests/cases/shared/test_public_audit.py"}


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    detail: str

    def line(self) -> str:
        return f"[{self.category}] {self.path}: {self.detail}"


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]


def voice_terms() -> tuple[str, ...]:
    """Ids longer than MIN_VOICE_ID; shorter ones collide with ordinary words."""
    ids = {value for value in inputs.voice_ids() if len(value) >= MIN_VOICE_ID}
    ids.update(stem for stem in inputs.character_cards() if len(stem) >= MIN_VOICE_ID)
    return tuple(sorted(ids))


def voice_patterns(words: tuple[str, ...]) -> str:
    """Alphanumeric boundaries, so `example_config` matches but `Summazzfixture` does not."""
    return "|".join(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])" for word in words)


def scan_text(path: str, text: str, words: tuple[str, ...]) -> list[Finding]:
    findings: list[Finding] = []
    suffix = Path(path).suffix.lower()
    is_doc = suffix in DOC_SUFFIXES

    for match in SECRETS.finditer(text):
        findings.append(Finding("secrets", path, match.group(0)[:12] + "..."))
    for match in CREDENTIALS.finditer(text):
        value = match.group(1)
        if value.startswith("${") or value.lower() in {"noop", "test", "dummy", "changeme", "example", "none"}:
            continue
        if len(value) >= 6:
            findings.append(Finding("credentials", path, f"{match.group(0).split(':')[0]}: non-empty"))
    for match in HOME_PATHS.finditer(text):
        findings.append(Finding("home-path", path, match.group(0)))
    if not is_doc and path.startswith(CONFIG_PREFIX):
        for match in MACHINE_PATHS.finditer(text):
            findings.append(Finding("machine-path", path, f"{match.group(0)} (use {{AI_ROOT}})"))
    for match in PRIVATE_WORDS.finditer(text):
        findings.append(Finding("private-word", path, match.group(0)))
    for word in words:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.I):
            findings.append(Finding("private-input", path, word))
    return findings


def audit(root: Path) -> list[Finding]:
    words = voice_terms()
    findings: list[Finding] = []
    for path in tracked_files(root):
        if path.split("/")[0] in IGNORED_ROOTS or any(path.startswith(prefix) for prefix in IGNORED_ROOTS):
            findings.append(Finding("ignored-tracked", path, "path belongs to an ignored folder"))
            continue
        if path in SELF_REFERENTIAL or any(path.startswith(prefix) for prefix in ALLOWLIST):
            continue
        full = root / path
        if not full.is_file():
            # - a pending deletion in the working tree; git status owns that state
            continue
        suffix = full.suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        if full.stat().st_size > LARGE_FILE_BYTES:
            findings.append(Finding("large-file", path, f"{full.stat().st_size // 1024} KB tracked"))
        findings.extend(scan_text(path, full.read_text(encoding="utf-8", errors="ignore"), words))
    return findings


def history_findings(root: Path) -> list[Finding]:
    """Paths that carried an audited pattern in any commit; only a rewrite removes them."""
    pattern = "|".join(
        [
            SECRETS.pattern,
            HOME_PATHS.pattern,
            PRIVATE_WORDS.pattern,
            voice_patterns(voice_terms()),
        ]
    )
    revs = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--all"], capture_output=True, text=True, check=True
    ).stdout.split()
    if not revs:
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "grep", "-I", "-l", "-i", "-E", pattern, *revs],
        capture_output=True,
        text=True,
    )
    seen: dict[str, str] = {}
    for line in result.stdout.splitlines():
        rev, _, path = line.partition(":")
        if path in SELF_REFERENTIAL or any(path.startswith(prefix) for prefix in ALLOWLIST):
            continue
        seen.setdefault(path, rev[:7])
    return [Finding("history", path, f"still in commit {rev}") for path, rev in sorted(seen.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--history", action="store_true", help="also scan every commit")
    args = parser.parse_args()
    findings = audit(project_cfg.BASE_DIR)
    if args.history:
        findings.extend(history_findings(project_cfg.BASE_DIR))
    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], indent=2))
    else:
        for finding in findings:
            print(finding.line())
        print(f"\n{len(findings)} finding(s); a clean tree prints nothing")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
