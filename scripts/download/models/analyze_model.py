"""Inspect registered/installed models into one sourced, incremental metadata inventory."""

import argparse
import json
import shutil
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg
from scripts.config.models import model_languages
from scripts.download.models import metadata_evidence, metadata_formats, metadata_sources, metadata_summary, model_sync

VERSION = 1


def discover(groups=None, paths=()):
    roots = {key: root for key, root in model_sync.MODEL_ROOTS.items()
             if not groups or any(key == group or key.startswith(group + "/") for group in groups)}
    records = {}
    for model in model_cfg.MODELS:
        if groups and not any(model.group == group or model.group.startswith(group + "/") for group in groups):
            continue
        if model.path.suffix.lower() not in model_sync.MODEL_SUFFIXES:
            continue
        key = str(model.path.resolve())
        row = records.setdefault(key, {"path": key, "ids": [], "groups": [], "registry": []})
        row["ids"].append(model.label)
        if model.group not in row["groups"]:
            row["groups"].append(model.group)
        row["registry"].append({"id": model.label, "url": model.url, "notes": model.notes, "sha256": model.sha256,
                                "roles": list(model.roles), "runtimes": list(model.runtimes)})
    files = model_sync.installed_model_files(roots)
    for path in paths:
        path = path.resolve()
        files.update(model_sync.installed_model_files({"explicit": path}) if path.is_dir() else [path])
    for path in files:
        key = str(path)
        owners = [group for group, root in roots.items() if path.is_relative_to(root.resolve())]
        records.setdefault(key, {"path": key, "ids": [], "groups": owners, "registry": []})
    return records


def inspect_record(row, previous, *, refresh=False, full_arrays=False, tensor_index=False, native=False):
    path = Path(row["path"])
    record = {**row, "checked_at": datetime.now(UTC).isoformat()}
    record.update(measured_metadata=previous.get('measured_metadata', []), previous_paths=previous.get('previous_paths', []))
    if not path.is_file():
        return {**record, "status": "missing", "local": {}, "sidecars": [], "hub": previous.get("hub", [])}
    stat = path.stat()
    signature = {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "analyzer_version": VERSION,
                 "full_arrays": full_arrays, "tensor_index": tensor_index}
    record.update(file=signature, hub=previous.get("hub", []))
    cached = not refresh and previous.get("file") == signature and previous.get("status") == "ok"
    try:
        record["local"] = previous["local"] if cached else metadata_formats.inspect(path, full_arrays=full_arrays, tensor_index=tensor_index)
        record["status"] = "ok"
        record["cache_hit"] = cached
    except (OSError, ValueError, KeyError, OverflowError, struct.error, TypeError) as error:
        record.update(status="error", local={"error": str(error)})
    record["sidecars"] = metadata_formats.sidecars(path)
    record["native"] = previous.get("native", {})
    if native:
        try:
            record["native"] = metadata_sources.native_metadata(path, row["groups"])
        except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
            record["native"] = {"status": "error", "error": str(error)}
    return record


def enrich_hub(records, cache):
    jobs = {}
    for record in records.values():
        for source in record["registry"]:
            hub = metadata_sources.hub_source(source["url"])
            if hub:
                jobs[(hub.repo_id, hub.revision, hub.filename.rpartition('/')[0])] = hub

    def fetch(item):
        key, source = item
        try:
            result = metadata_sources.hub_metadata(source)
            result.update(status="ok", checked_at=datetime.now(UTC).isoformat())
        except Exception as error:
            result = {"status": "error", "repo": source.repo_id, "requested_revision": source.revision, "error": str(error)}
        return "@".join(key), result

    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, result in pool.map(fetch, jobs.items()):
            # Preserve last good metadata on transient/network errors and retain the new error.
            if result["status"] == "error" and cache.get(key, {}).get("status") == "ok":
                cache[key]["last_error"] = result
            else:
                cache[key] = result
    for record in records.values():
        keys = set()
        for source in record["registry"]:
            hub = metadata_sources.hub_source(source["url"])
            if hub:
                keys.add("@".join((hub.repo_id, hub.revision, hub.filename.rpartition('/')[0])))
        record["hub"] = [cache[key] for key in sorted(keys) if key in cache]


def save_inventory(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    if path.is_file():
        trash = (project_cfg.BASE_DIR / "trash/shared/model_metadata").resolve()
        backup = (trash / f"{path.stem}-{time.time_ns()}.json").resolve()
        if not backup.is_relative_to(trash):
            raise ValueError("Metadata backup escaped its trash directory")
        trash.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", nargs="+", help="Canonical group prefixes: asr, audiocpp, tts, llamacpp, ...")
    parser.add_argument("--model", nargs="+", help="Canonical ID/name substring; unselected saved records are retained")
    parser.add_argument("--path", nargs="+", type=Path, default=[], help="Additional file/directory to inspect")
    parser.add_argument("--hub", action="store_true", help="Refresh public model cards/configs; no weight downloads")
    parser.add_argument("--native", action="store_true", help="Use verified metadata-only runtime inspectors (native context)")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached file-header inspection")
    parser.add_argument("--measurements", nargs="*", type=Path, help="Import saved report.json evidence; no arguments scans test outputs; never runs tests")
    parser.add_argument("--full-arrays", action="store_true", help="Retain full vocab/metadata arrays; output may be very large")
    parser.add_argument("--tensor-index", action="store_true", help="Include tensor names/shapes/types/offsets, never payloads")
    parser.add_argument("--output", type=Path, default=project_cfg.component("shared").state_dir / "model_metadata.json")
    args = parser.parse_args(argv)
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.is_file() else {}
    saved = previous.get("models", {})
    candidates = discover(args.group, args.path)
    selected = {key: row for key, row in candidates.items() if not args.model or any(
        query.lower() in " ".join([row["path"], *row["ids"]]).lower() for query in args.model)}
    if not selected:
        parser.error("No matching models; saved inventory was not changed")
    rows = {}
    for index, (key, row) in enumerate(sorted(selected.items()), 1):
        # Relocated catalog files keep source/evidence identity; old snapshots remain in trash.
        if key not in saved and Path(key).is_file():
            urls = {item['url'] for item in row['registry'] if item['url']}
            relocated = [old_key for old_key, old in saved.items() if old_key != key
                         and Path(old_key).name == Path(key).name and not Path(old_key).exists()
                         and urls & {item.get('url') for item in old.get('registry', [])}]
            if len(relocated) == 1:
                old_key = relocated[0]
                saved[key] = saved.pop(old_key)
                saved[key].setdefault('previous_paths', []).append(old_key)
                saved[key]['native'] = {}
        print(f"[{index}/{len(selected)}] {row['ids'][0] if row['ids'] else Path(key).name}", flush=True)
        rows[key] = inspect_record(row, saved.get(key, {}), refresh=args.refresh, full_arrays=args.full_arrays,
                                   tensor_index=args.tensor_index, native=args.native)
    hub_cache = previous.get("hub_sources", {})
    if args.hub:
        enrich_hub(rows, hub_cache)
    catalog = model_languages.read_catalog()
    for row in rows.values():
        row["summary"] = metadata_summary.summary(row, catalog)
    metadata_evidence.published(rows)
    saved.update(rows)
    evidence_errors = metadata_evidence.measurements(saved, args.measurements or [project_cfg.TESTS_DIR / 'output']) if args.measurements is not None else []
    inventory: dict[str, Any] = {"schema_version": VERSION, "updated_at": datetime.now(UTC).isoformat(),
        "scope": "Registered and discovered installed model files; optional missing checkpoints remain explicit.",
        "run": {"groups": args.group, "models": args.model, "hub": args.hub, "native": args.native,
                "selected_count": len(rows), "ok": sum(r["status"] == "ok" for r in rows.values()),
                "missing": sum(r["status"] == "missing" for r in rows.values()),
                "errors": sum(r["status"] == "error" for r in rows.values())}, "models": saved, "hub_sources": hub_cache,
                "measurement_import_errors": evidence_errors}
    save_inventory(args.output, inventory)
    print(f"[OK] Saved {len(saved)} records -> {args.output}; current scan: {inventory['run']}")
    return 1 if inventory["run"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
