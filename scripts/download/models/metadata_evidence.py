"""Attach published quality and existing measured evidence without running benchmarks."""

import json
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.download.models.metadata_formats import json_file

QUALITY_FILE = project_cfg.CONFIG_DIR / "models/model_quality.json"


def published(records):
    catalog = json.loads(QUALITY_FILE.read_text(encoding="utf-8"))
    for row in records.values():
        row["published_quality"] = [entry for entry in catalog["results"] if set(entry["model_ids"]) & set(row["ids"])]


def _evidence_files(paths) -> set[Any]:
    files = set()
    for path in paths:
        files.update(path.rglob("report.json") if path.is_dir() else [path])
    return files


def _identity_lookup(records) -> dict[str, str]:
    lookup = {}
    for key, record in records.items():
        for identity in [record["path"], *record.get("previous_paths", []), *record["ids"]]:
            lookup[identity.replace("\\", "/").casefold()] = key
    return lookup


def _evidence_entry(path, report, result, index, context) -> dict[str, Any]:
    return {
        "source": str(path.resolve()),
        "result_index": index,
        "report_mtime_ns": path.stat().st_mtime_ns,
        "execution_context": context,
        "conditions": {
            field: report[field]
            for field in (
                "settings",
                "hardware",
                "clips",
                "clip",
                "limits",
                "group",
                "measurement_scope",
                "language_override",
            )
            if field in report
        },
        "checkpoint_match": "recorded identity/path; current file hash not revalidated",
        "data": {field: value for field, value in result.items() if field != "events"},
        "limits": [
            "Missing RAM/VRAM/CPU counters remain unknown; file size is not runtime memory.",
            "Preserve timing scopes; startup/loading and real-time audio pacing are not decode speed.",
        ],
    }


def _apply_result(records, lookup, path, report, index, result) -> None:
    if not isinstance(result, dict):
        return
    identity = result.get("model_id") or result.get("model_path") or result.get("model")
    if not isinstance(identity, str):
        return
    key = lookup.get(identity.replace("\\", "/").casefold())
    if key is None:
        return
    # Raw evidence retains its own scope/status; cold/failed data never becomes resident speed.
    entry = _evidence_entry(path, report, result, index, report.get("execution_context"))
    target = records[key].setdefault("measured_metadata", [])
    target[:] = [old for old in target if (old["source"], old["result_index"]) != (entry["source"], index)]
    target.append(entry)


def _merge_report(records, lookup, path, report) -> None:
    if not report.get("execution_context"):
        return
    results = report.get("results", [])
    if not isinstance(results, list):
        return
    for index, result in enumerate(results):
        _apply_result(records, lookup, path, report, index, result)


def measurements(records, paths):
    """Only explicit checkpoint identities and recorded context; never infer missing memory."""
    lookup = _identity_lookup(records)
    errors = []
    for path in sorted(_evidence_files(paths)):
        try:
            report = json_file(path)
            if isinstance(report, dict):
                _merge_report(records, lookup, path, report)
        except (OSError, ValueError, TypeError) as error:
            errors.append({"source": str(path), "error": str(error)})
    return errors
