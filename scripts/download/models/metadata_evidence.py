"""Attach published quality and existing measured evidence without running benchmarks."""

import json
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.download.models.metadata_formats import json_file

QUALITY_FILE = project_cfg.CONFIG_DIR / 'models/model_quality.json'


def published(records):
    catalog = json.loads(QUALITY_FILE.read_text(encoding='utf-8'))
    for row in records.values():
        row['published_quality'] = [entry for entry in catalog['results']
                                    if set(entry['model_ids']) & set(row['ids'])]


def measurements(records, paths):
    """Only explicit checkpoint identities and recorded context; never infer missing memory."""
    files = set()
    errors = []
    for path in paths:
        files.update(path.rglob('report.json') if path.is_dir() else [path])
    lookup = {}
    for key, record in records.items():
        for identity in [record['path'], *record.get('previous_paths', []), *record['ids']]:
            lookup[identity.replace('\\', '/').casefold()] = key
    for path in sorted(files):
        try:
            report = json_file(path)
            if not isinstance(report, dict):
                continue
            context = report.get('execution_context')
            if not context:
                continue
            results = report.get('results', [])
            if not isinstance(results, list):
                continue
            for index, result in enumerate(results):
                if not isinstance(result, dict):
                    continue
                identity = result.get('model_id') or result.get('model_path') or result.get('model')
                if not isinstance(identity, str):
                    continue
                key = lookup.get(identity.replace('\\', '/').casefold())
                if key is None:
                    continue
                # Raw evidence retains its own scope/status; cold/failed data never becomes resident speed.
                entry: dict[str, Any] = {
                    'source': str(path.resolve()), 'result_index': index,
                    'report_mtime_ns': path.stat().st_mtime_ns,
                    'execution_context': context,
                    'conditions': {field: report[field] for field in ('settings', 'hardware', 'clips', 'clip', 'limits', 'group', 'measurement_scope', 'language_override') if field in report},
                    'checkpoint_match': 'recorded identity/path; current file hash not revalidated',
                    'data': {field: value for field, value in result.items() if field != 'events'},
                    'limits': ['Missing RAM/VRAM/CPU counters remain unknown; file size is not runtime memory.',
                               'Preserve timing scopes; startup/loading and real-time audio pacing are not decode speed.'],
                }
                target = records[key].setdefault('measured_metadata', [])
                target[:] = [old for old in target if (old['source'], old['result_index']) != (entry['source'], index)]
                target.append(entry)
        except (OSError, ValueError, TypeError) as error:
            errors.append({'source': str(path), 'error': str(error)})
    return errors
