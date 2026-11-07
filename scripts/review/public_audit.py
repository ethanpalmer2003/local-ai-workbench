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

from scripts.config import overlay_inputs as inputs
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
# - the vocabulary itself is personal, so it lives in the overlay; this file names no term
PRIVATE_WORDS_SETTING = "review.private_words"

# - prefix -> why the hit is expected; keep this list short and specific
ALLOWLIST = {
    "scripts/config/llamacpp/hrx-patches/": "recorded paths from a completed build run; evidence, not live config"
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
    """Alphanumeric boundaries, so `chapter_config` matches but `Summazzfixture` does not."""
    return "|".join(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])" for word in words)


def private_words() -> tuple[str, ...]:
    """Vocabulary supplied by the overlay's defaults.json; nothing personal is committed here."""
    configured = inputs.setting(PRIVATE_WORDS_SETTING, [])
    return tuple(str(word) for word in configured if str(word).strip())


PLACEHOLDER_VALUES = {"noop", "test", "dummy", "changeme", "example", "none"}


def _secret_findings(path: str, text: str) -> list[Finding]:
    return [Finding("secrets", path, match.group(0)[:12] + "...") for match in SECRETS.finditer(text)]


def _credential_findings(path: str, text: str) -> list[Finding]:
    findings = []
    for match in CREDENTIALS.finditer(text):
        value = match.group(1)
        if value.startswith("${") or value.lower() in PLACEHOLDER_VALUES:
            continue
        if len(value) >= 6:
            findings.append(Finding("credentials", path, f"{match.group(0).split(':')[0]}: non-empty"))
    return findings


def _path_findings(path: str, text: str) -> list[Finding]:
    findings = [Finding("home-path", path, match.group(0)) for match in HOME_PATHS.finditer(text)]
    if Path(path).suffix.lower() in DOC_SUFFIXES or not path.startswith(CONFIG_PREFIX):
        return findings
    findings.extend(
        Finding("machine-path", path, f"{match.group(0)} (use {{AI_ROOT}})") for match in MACHINE_PATHS.finditer(text)
    )
    return findings


def _word_findings(path: str, text: str, words: tuple[str, ...]) -> list[Finding]:
    findings = [
        Finding("private-word", path, word)
        for word in private_words()
        if re.search(voice_patterns((word,)), text, re.I)
    ]
    findings.extend(
        Finding("private-input", path, word) for word in words if re.search(voice_patterns((word,)), text, re.I)
    )
    return findings


def scan_text(path: str, text: str, words: tuple[str, ...]) -> list[Finding]:
    return [
        *_secret_findings(path, text),
        *_credential_findings(path, text),
        *_path_findings(path, text),
        *_word_findings(path, text, words),
    ]


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


def history_findings(root: Path, extra_terms: tuple[str, ...] = ()) -> list[Finding]:
    """Paths that carried an audited pattern in any commit; only a rewrite removes them."""
    vocabulary = [voice_patterns(voice_terms()), *[voice_patterns((term,)) for term in extra_terms]]
    if private_words():
        vocabulary.append(voice_patterns(private_words()))
    pattern = "|".join([SECRETS.pattern, HOME_PATHS.pattern, *vocabulary])
    revs = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--all"], capture_output=True, text=True, check=True
    ).stdout.split()
    if not revs:
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "grep", "-I", "-l", "-i", "-E", pattern, *revs], capture_output=True, text=True
    )
    seen: dict[str, str] = {}
    for line in result.stdout.splitlines():
        rev, _, path = line.partition(":")
        if path in SELF_REFERENTIAL or any(path.startswith(prefix) for prefix in ALLOWLIST):
            continue
        seen.setdefault(path, rev[:7])
    return [Finding("history", path, f"still in commit {rev}") for path, rev in sorted(seen.items())]


def identity_terms() -> tuple[str, ...]:
    """This machine's account name and git identity; personal identifiers a clone would inherit."""
    terms = [Path.home().name]
    email = subprocess.run(
        ["git", "-C", str(project_cfg.BASE_DIR), "config", "user.email"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if email:
        terms.append(email)
    return tuple(term for term in terms if len(term) >= 4)


def scrub_findings(root: Path) -> list[Finding]:
    """Tree and history, this machine's identity included; run before a repository goes public."""
    extra = identity_terms()
    findings = audit(root)
    for term in extra:
        pattern = rf"(?i)(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        for path in tracked_files(root):
            if path in SELF_REFERENTIAL:
                continue
            target = root / path
            if not target.is_file() or target.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if re.search(pattern, target.read_text(encoding="utf-8", errors="ignore")):
                findings.append(Finding("identity", path, f"contains {term}"))
    findings.extend(history_findings(root, extra_terms=extra))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--history", action="store_true", help="also scan every commit")
    parser.add_argument("--scrub", action="store_true", help="tree and history, identity terms included")
    args = parser.parse_args(argv)
    findings = scrub_findings(project_cfg.BASE_DIR) if args.scrub else audit(project_cfg.BASE_DIR)
    if args.history and not args.scrub:
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
