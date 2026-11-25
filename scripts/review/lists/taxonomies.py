"""The category systems the repo owns, as data, so overlap is computed, not eyeballed.

Every taxonomy names its code owner and reads its members from that owner: no second
machine-readable copy. Kinds follow notes/GROUPINGS-INDEX.md: label families are the closed
value sets a second file reads, entry kinds classify entry_points.ALL, and the check-run and
selection sets classify suites, targets and engines. main() diffs every pair for shared
members and keeps the index's family table honest, so it is the taxonomy gate section.
"""

from dataclasses import dataclass
from pathlib import Path

from scripts.benchmarks.asr.coverage import coverage
from scripts.benchmarks.shared.paths import Outcome
from scripts.config import models
from scripts.config import project_config as project_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.config.models import catalog, model_languages
from scripts.config.shared import deferred as parked
from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg
from scripts.review.lists import entry_points
from scripts.tests.cases.suites import live_frameworks, quick_validation
from scripts.tests.shared.native_suites import SUITES
from scripts.tools import capability_matrix

GROUPINGS_INDEX = project_cfg.BASE_DIR / "notes" / "GROUPINGS-INDEX.md"


@dataclass(frozen=True)
class Taxonomy:
    """One category system: its kind, its owner, and its live members."""

    name: str
    kind: str
    owner: str
    members: frozenset[str]


def build_taxonomies() -> dict[str, Taxonomy]:
    """Every known taxonomy, read from its owner."""
    rows = coverage()
    return {
        "Catalog category": Taxonomy(
            "Catalog category", "label", "scripts/config/models/catalog.py", frozenset(catalog.CATEGORIES)
        ),
        "Catalog role": Taxonomy(
            "Catalog role",
            "label",
            "scripts/config/models/catalog.py",
            frozenset(role for row in models.MODELS for role in row.roles),
        ),
        "Deferred": Taxonomy(
            "Deferred",
            "label",
            "scripts/config/shared/deferred.py",
            frozenset(item.value for item in parked.DeferredKind)
            | frozenset(item.value for item in parked.DeferredCause),
        ),
        "Delivery mode": Taxonomy(
            "Delivery mode", "label", "scripts/config/shared/speech_delivery.py", frozenset(speech_delivery.MODES)
        ),
        "Language tier": Taxonomy(
            "Language tier",
            "label",
            "scripts/config/models/model_languages.json",
            frozenset(
                key for row in model_languages.read_catalog()["models"] for key in (row.get("coverage_tiers") or {})
            ),
        ),
        "Run outcome": Taxonomy(
            "Run outcome", "label", "scripts/benchmarks/shared/paths.py", frozenset(item.value for item in Outcome)
        ),
        "Speech class": Taxonomy(
            "Speech class",
            "label",
            "scripts/config/models/catalog.py",
            frozenset(item.value for item in catalog.SpeechClass),
        ),
        "Test readiness": Taxonomy(
            "Test readiness", "label", "scripts/benchmarks/asr/coverage.py", frozenset(row["status"] for row in rows)
        ),
        "Test runner": Taxonomy(
            "Test runner", "label", "scripts/benchmarks/asr/coverage.py", frozenset(row["runner"] for row in rows)
        ),
        "Workflow profile": Taxonomy(
            "Workflow profile", "label", "scripts/launchers/launcher_config.py", frozenset(cfg.PROFILE_REQUIREMENTS)
        ),
        "Test suite": Taxonomy("Test suite", "check-run", "scripts/tests/shared/native_suites.py", frozenset(SUITES)),
        "Launcher target": Taxonomy(
            "Launcher target",
            "check-run",
            "scripts/tests/cases/suites/live_frameworks.py",
            frozenset(live_frameworks.LAUNCHER_TARGETS),
        ),
        "Backend probe": Taxonomy(
            "Backend probe",
            "check-run",
            "scripts/tests/cases/suites/quick_validation.py",
            frozenset(quick_validation.PROBES),
        ),
        "Budget class": Taxonomy(
            "Budget class",
            "check-run",
            "scripts/tools/capability_matrix.py",
            frozenset(capability_matrix.CATEGORY.values()),
        ),
        "Capability section": Taxonomy(
            "Capability section",
            "check-run",
            "scripts/tools/capability_matrix.py",
            frozenset(capability_matrix.SECTION.values()),
        ),
        "ASR engine": Taxonomy(
            "ASR engine",
            "selection",
            "scripts/benchmarks/asr/coverage.py",
            frozenset(row["engine"] for row in rows) | frozenset(ASR_FILE_PROFILES),
        ),
        "Entry-point kind": Taxonomy(
            "Entry-point kind", "entry", "scripts/review/lists/entry_points.py", frozenset(entry_points.ALL.values())
        ),
        "Entry point": Taxonomy(
            "Entry point", "entry", "scripts/review/lists/entry_points.py", frozenset(entry_points.ALL)
        ),
        "File set": Taxonomy(
            "File set", "entry", "scripts/shared/file_sets.py", frozenset({"maintained", "tracked", "text", "changed"})
        ),
    }


# - shared members the owners intend: the same word in two systems on purpose
KNOWN_OVERLAPS: dict[frozenset[str], str] = {
    frozenset({"Backend probe", "Catalog category"}): "the images probe is named after the model family it tests",
    frozenset({"Catalog role", "Workflow profile"}): "the coding profile is named after the role it serves",
    frozenset({"Speech class", "Test runner"}): "both use none for absent",
}


def overlapping(taxonomies: dict[str, Taxonomy]) -> list[tuple[str, str, frozenset[str]]]:
    """Taxonomy pairs sharing at least one member, minus the intended ones."""
    names = sorted(taxonomies)
    found = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            shared = taxonomies[left].members & taxonomies[right].members
            if shared and frozenset((left, right)) not in KNOWN_OVERLAPS:
                found.append((left, right, shared))
    return found


def index_families(path: Path = GROUPINGS_INDEX) -> set[str]:
    """The Family column of the groupings index, which the label taxonomies must match exactly."""
    families = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        first = line.split("|")[1].strip()
        if first and first != "Family" and not set(first) <= set("-: "):
            families.add(first)
    return families


def index_drift(taxonomies: dict[str, Taxonomy], path: Path = GROUPINGS_INDEX) -> set[str]:
    """Families the index and the registry disagree on, in either direction."""
    labels = {name for name, taxonomy in taxonomies.items() if taxonomy.kind == "label"}
    return labels ^ index_families(path)


def main(argv: list[str] | None = None) -> int:
    """Diff every taxonomy pair and the index; a new shared member or a drifted family fails."""
    _ = argv
    known = build_taxonomies()
    status = 0
    for left, right, shared in overlapping(known):
        owners = f"{known[left].owner} vs {known[right].owner}"
        print(f"[FAIL] {left} <-> {right} share {sorted(shared)} ({owners})")
        status = 1
    for family in sorted(index_drift(known)):
        print(f"[FAIL] family drift: {family} is in the code registry or the index, not both")
        status = 1
    if status:
        print("[NEXT] record an intended overlap in taxonomies.KNOWN_OVERLAPS, or rename one side")
        return 1
    print(f"[OK] {len(known)} taxonomies, {len(KNOWN_OVERLAPS)} intended overlap(s), index matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
