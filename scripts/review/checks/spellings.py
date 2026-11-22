"""Reject British spellings in text that ships, so one spelling reaches every reader.

- The repository writes American English: `quantization`, `behavior`, `catalog`, `analyze`
- Both spellings are correct English, so this is a convention check rather than a typo check;
  the point is that one spelling is used everywhere instead of drifting by author or by file
- A word in the pinned corpus is third-party text and stays as written
"""

import re
from pathlib import Path

from scripts.review.lists import text_files

# - British form -> American form; each entry is matched as a whole word, case preserved
VARIANTS: dict[str, str] = {
    "analyse": "analyze",
    "analysed": "analyzed",
    "analysing": "analyzing",
    "apologise": "apologize",
    "artefact": "artifact",
    "artefacts": "artifacts",
    "authorise": "authorize",
    "authorised": "authorized",
    "behaviour": "behavior",
    "behaviours": "behaviors",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "catalogue": "catalog",
    "catalogued": "cataloged",
    "catalogues": "catalogs",
    "categorise": "categorize",
    "categorised": "categorized",
    "centre": "center",
    "centres": "centers",
    "characterise": "characterize",
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
    "neighbours": "neighbors",
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
    "summarise": "summarize",
    "summarised": "summarized",
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
    "characterisation": "characterization",
    "characterisations": "characterizations",
    "customisation": "customization",
    "finalisation": "finalization",
    "generalisations": "generalizations",
    "generalise": "generalize",
    "globalise": "globalize",
    "initialisation": "initialization",
    "initialisations": "initializations",
    "legalise": "legalize",
    "localisation": "localization",
    "localise": "localize",
    "maximisation": "maximization",
    "minimisation": "minimization",
    "mobilisation": "mobilization",
    "normalisation": "normalization",
    "organisation": "organization",
    "organisations": "organizations",
    "popularise": "popularize",
    "prioritisation": "prioritization",
    "randomise": "randomize",
    "realisation": "realization",
    "specialise": "specialize",
    "stabilisation": "stabilization",
    "standardisation": "standardization",
    "synthesise": "synthesize",
    "synthesised": "synthesized",
    "synthesises": "synthesizes",
    "synthesising": "synthesizing",
    "tokenisation": "tokenization",
    "tolerise": "tolerize",
    "utilisation": "utilization",
    "visualisation": "visualization",
    "whilst": "while",
    "worshipped": "worshiped",
}
PATTERN = re.compile(r"\b(" + "|".join(sorted(VARIANTS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
# - the checker and its fixtures quote British forms on purpose
SELF_REFERENTIAL = {"scripts/review/checks/spellings.py", "scripts/tests/cases/review/checks/test_spellings.py"}


def american(match: re.Match[str]) -> str:
    """The American form, keeping the case the writer used."""
    word = match.group(0)
    replacement = VARIANTS[word.lower()]
    if word.isupper():
        return replacement.upper()
    if word[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def scan_text(path: str, text: str) -> list[tuple[int, str, str]]:
    """Line, British form and American form for every variant this file would publish."""
    findings = []
    for number, line in enumerate(text_files.mask_corpus_references(path, text).splitlines(), 1):
        findings.extend((number, match.group(0), american(match)) for match in PATTERN.finditer(line))
    return findings


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
    root, paths = text_files.text_check_targets(argv, __doc__, SELF_REFERENTIAL)
    return check(root, paths)


if __name__ == "__main__":
    raise SystemExit(main())
