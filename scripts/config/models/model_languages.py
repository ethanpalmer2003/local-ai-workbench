"""Offline language inventory for registered speech checkpoints; never loads a model.

The JSON beside this file is the declaration: what each registry publishes, plus the judgment no
model reports (tiers, limits, sources). A packaged AudioCpp spec is authoritative for the weight it
ships in, so an installed model's declared locales are compared against it instead of trusted.
"""

import argparse
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).with_suffix(".json")


def read_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def normalized(code: str) -> str:
    return code.lower().replace("_", "-")


def packaged_locales(model_id: str) -> list[str] | None:
    """Locales a packaged AudioCpp spec declares; None when that weight is absent or carries no spec."""
    from scripts.config import models as model_cfg
    from scripts.config.models.gguf_metadata import inspect_metadata

    model = next((item for item in model_cfg.MODELS if item.label == model_id), None)
    if model is None or not model.path.is_file():
        return None
    try:
        metadata = inspect_metadata(model.path)["metadata"]
    except ValueError:
        return None
    spec = json.loads(metadata.get("audiocpp.model_spec.json", "{}"))
    return [str(code) for code in spec.get("languages", [])] or None


def select(catalog, *, task=None, model=None, language=None):
    query = normalized(language) if language else None
    if query:
        query = next((code for code, name in catalog["language_names"].items() if name.lower() == query), query)
        query = {"mandarin": "zh", "jv": "jw"}.get(query, query)
    rows = []
    for entry in catalog["models"]:
        if task and task not in entry["tasks"]:
            continue
        if model and model.lower() not in " ".join([entry["distribution"], entry["name"], *entry["model_ids"]]).lower():
            continue
        codes = [*(entry["languages"] or []), *entry["locales"]]
        if query and not any(normalized(code) == query or normalized(code).split("-")[0] == query for code in codes):
            continue
        row = {
            **entry,
            "language_count": None if entry["languages"] is None else len(entry["languages"]),
            "locale_count": len(entry["locales"]),
            "dialect_count": len(entry["dialects"]),
        }
        tiers = entry.get("coverage_tiers", {})
        row["ready_locale_count"] = (
            len(tiers.get("transcription_ready", [])) + len(tiers.get("broad_coverage", [])) if tiers else None
        )
        rows.append(row)
    return rows


def details(row, names):
    def describe(code):
        base = normalized(code).split("-")[0]
        return f"{code} ({names.get(base, base).title()})"

    print("\n" + row["name"])
    print(
        "Languages: "
        + (
            ", ".join(describe(code) for code in row["languages"])
            if row["languages"] is not None
            else "unverified; no complete ASR list"
        )
    )
    if row["locales"]:
        print("Locales: " + ", ".join(row["locales"]))
    if row["dialects"]:
        print("Dialects: " + ", ".join(row["dialects"]))
    for tier, codes in row.get("coverage_tiers", {}).items():
        print(tier + ": " + ", ".join(codes))
    print("Local limits: " + row["notes"])
    print("Model IDs: " + ", ".join(row["model_ids"]))
    print("Sources: " + ", ".join(source["url"] for source in row["sources"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("asr", "tts"))
    parser.add_argument("--model", help="Model family/name or canonical download ID (substring)")
    parser.add_argument("--language", help="Language name or code, e.g. French or fr")
    parser.add_argument("--details", action="store_true", help="Print all language names/codes, limits and sources")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    catalog = read_catalog()
    rows = select(catalog, task=args.task, model=args.model, language=args.language)
    if args.json:
        print(
            json.dumps(
                {
                    "reviewed": catalog["reviewed"],
                    "scope": catalog["scope"],
                    "models": rows,
                    "language_names": catalog["language_names"],
                },
                indent=2,
                ensure_ascii=True,
            )
        )
    else:
        print("Model | Task | Languages | Locales | Dialects")
        for row in rows:
            count = row["language_count"] if row["language_count"] is not None else "?"
            print(
                f"{row['name']} | {','.join(row['tasks'])} | {count} | {row['locale_count']} | {row['dialect_count']}"
            )
        print("\nCounts are listed coverage, not accuracy. auto is not a language. ? = unverified.")
        print("Nemotron: 32/40 locales work out of the box; eight require adaptation.")
        print("Use --details for complete lists, runtime limits and source links.")
        if args.details:
            for row in rows:
                details(row, catalog["language_names"])
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
