"""Reject British spellings in text that ships, so one spelling reaches every reader.

- The repository writes American English: `quantization`, `behavior`, `catalog`, `analyze`
- Both spellings are correct English, so this is a convention check rather than a typo check;
  the point is that one spelling is used everywhere instead of drifting by author or by file
- A word in the pinned corpus is third-party text and stays as written
"""

import argparse
import re
import subprocess
from pathlib import Path

# - British form -> American form; each entry is matched as a whole word, case preserved
VARIANTS: dict[str, str] = {
    "analyse": "analyze",
    "analysed": "analyzed",
    "analysing": "analyzing",
    "apologise": "apologize",
    "artefact": "artifact",
    "artefacts": "artifacts",
    "authozzfixture": "authorize",
    "authozzfixtured": "authorized",
    "behaviour": "behavior",
    "behaviours": "behaviors",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "catalogue": "catalog",
    "catalogued": "cataloged",
    "catalogues": "catalogs",
    "categozzfixture": "categorize",
    "categozzfixtured": "categorized",
    "centre": "center",
    "centres": "centers",
    "charactezzfixture": "characterize",
    "colour": "color",
    "colours": "colors",
    "criticise": "criticize",
    "customise": "customize",
    "customised": "customized",
    "defence": "defense",
    "emphasise": "emphasize",
    "emphasised": "emphasized",
    "favour": "favor",
    "favoured": "favored",
    "fibre": "fiber",
    "finalise": "finalize",
    "finalised": "finalized",
    "fulfil": "fulfill",
    "grey": "gray",
    "honour": "honor",
    "initialise": "initialize",
    "initialised": "initialized",
    "initialises": "initializes",
    "initialising": "initializing",
    "judgement": "judgment",
    "labelled": "labeled",
    "labelling": "labeling",
    "labour": "labor",
    "licence": "license",
    "licences": "licenses",
    "maximise": "maximize",
    "minimise": "minimize",
    "minimised": "minimized",
    "mobilise": "mobilize",
    "modelling": "modeling",
    "modelled": "modeled",
    "neighbour": "neighbor",
    "normalise": "normalize",
    "normalised": "normalized",
    "offence": "offense",
    "optimise": "optimize",
    "optimised": "optimized",
    "optimisation": "optimization",
    "optimisations": "optimizations",
    "organise": "organize",
    "organised": "organized",
    "practise": "practice",
    "practised": "practiced",
    "practising": "practicing",
    "prioritise": "prioritize",
    "prioritised": "prioritized",
    "programme": "program",
    "programmes": "programs",
    "quantisation": "quantization",
    "quantisations": "quantizations",
    "quantise": "quantize",
    "quantised": "quantized",
    "quantises": "quantizes",
    "quantising": "quantizing",
    "realise": "realize",
    "realised": "realized",
    "recognise": "recognize",
    "recognised": "recognized",
    "recognises": "recognizes",
    "sanitise": "sanitize",
    "sanitised": "sanitized",
    "sceptical": "skeptical",
    "serialise": "serialize",
    "serialised": "serialized",
    "stabilise": "stabilize",
    "standardise": "standardize",
    "summazzfixture": "summarize",
    "summazzfixtured": "summarized",
    "symbolise": "symbolize",
    "synchronise": "synchronize",
    "synchronised": "synchronized",
    "theatre": "theater",
    "tokenise": "tokenize",
    "tokenised": "tokenized",
    "travelling": "traveling",
    "travelled": "traveled",
    "utilise": "utilize",
    "utilised": "utilized",
    "visualise": "visualize",
    "visualised": "visualized",
    "whilst": "while",
    "worshipped": "worshiped",
}
PATTERN = re.compile(r"\b(" + "|".join(sorted(VARIANTS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
CORPUS_FILE = "scripts/config/benchmarks/language_corpus.json"
REFERENCE_VALUE = re.compile(r'("reference"\s*:\s*")([^"\\]*(?:\\.[^"\\]*)*)(")')
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
    ".csv",
    ".html",
    ".css",
}


def american(match: re.Match[str]) -> str:
    """The American form, keeping the case the writer used."""
    word = match.group(0)
    replacement = VARIANTS[word.lower()]
    if word.isupper():
        return replacement.upper()
    if word[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def masked(text: str, path: str) -> str:
    """Quoted corpus references are third-party text and stay as written."""
    if path != CORPUS_FILE:
        return text
    return REFERENCE_VALUE.sub(lambda match: match.group(1) + "x" * len(match.group(2)) + match.group(3), text)


def scan_text(path: str, text: str) -> list[tuple[int, str, str]]:
    """Line, British form and American form for every variant this file would publish."""
    findings = []
    for number, line in enumerate(masked(text, path).splitlines(), 1):
        findings.extend((number, match.group(0), american(match)) for match in PATTERN.finditer(line))
    return findings


def is_text(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_SUFFIXES


def tracked_text_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True)
    # - a deletion is still in the index until it is committed; skip files the tree no longer has
    return [path for path in result.stdout.splitlines() if path and is_text(path) and (root / path).is_file()]


def check(root: Path, paths: list[str]) -> int:
    findings = [
        (path, number, found, american_form)
        for path in paths
        for number, found, american_form in scan_text(path, (root / path).read_text(encoding="utf-8", errors="ignore"))
    ]
    for path, number, found, american_form in findings:
        print(f"[FAIL] {path}:{number}: {found} -> {american_form}")
    print(f"{len(findings)} British spelling(s); write American English throughout")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files to check (default: every tracked text file)")
    args = parser.parse_args(argv)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    root = Path(top.stdout.strip())
    return check(root, args.paths or tracked_text_files(root))


if __name__ == "__main__":
    raise SystemExit(main())
