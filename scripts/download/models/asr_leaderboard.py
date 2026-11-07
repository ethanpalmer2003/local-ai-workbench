"""Export the public Open ASR tables, retaining filters, sources and publisher speed."""

import argparse
import csv
import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts.config import project_config as project_cfg

BASE = 'https://hf-audio-open-asr-leaderboard.hf.space'


def fetch(path, data=None):
    request = urllib.request.Request(BASE + path,
        json.dumps(data).encode() if data is not None else None,
        {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(16 * 1024 * 1024).decode('utf-8')


def plain(value):
    return html.unescape(re.sub('<[^>]+>', '', value)) if isinstance(value, str) else value


def export_table(folder, name, table):
    headers = [plain(value) for value in table['headers']]
    rows = [{key: plain(value) for key, value in zip(headers, row)} for row in table['data']]
    (folder / f'{name}.json').write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding='utf-8')
    with (folder / f'{name}.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-size', type=float, default=5)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = project_cfg.component('asr/shared').generated_dir / 'leaderboard' / stamp
    folder.mkdir(parents=True, exist_ok=True)
    config = json.loads(fetch('/config'))
    (folder / 'source-config.json').write_text(json.dumps(config, ensure_ascii=True), encoding='utf-8')
    components = config['components']
    # Discover the main table by semantic headers, rather than unstable component IDs.
    main_table = next(c for c in components if c['type'] == 'dataframe'
                      and 'Rank Δ' in c['props'].get('value', {}).get('headers', []))
    dependency = next(d for d in config['dependencies'] if d.get('api_name', '').startswith('_main_table_update')
                      and main_table['id'] in d.get('outputs', []))
    inputs = {c['id']: c['props'] for c in components}
    data = []
    for key in dependency['inputs']:
        props = inputs[key]
        label, value = props.get('label', ''), props.get('value')
        if label.startswith('Max size'):
            value = args.max_size
        elif label.startswith('Show proprietary'):
            value = False
        elif isinstance(value, list):
            value = [*value, 'Size (B)', '# Languages', 'License', 'Encoder', 'Decoder']
        data.append(value)
    call = json.loads(fetch('/gradio_api/call/' + dependency['api_name'], {'data': data}))
    events = fetch('/gradio_api/call/' + dependency['api_name'] + '/' + call['event_id'])
    (folder / 'filtered-response.sse').write_text(events, encoding='utf-8')
    complete = next(block for block in events.split('\n\n') if block.startswith('event: complete'))
    payload = json.loads(next(line[6:] for line in complete.splitlines() if line.startswith('data: ')))
    table = next(item.get('value', item) for item in payload if isinstance(item, dict)
                 and ('headers' in item or isinstance(item.get('value'), dict) and 'headers' in item['value']))
    rows = export_table(folder, 'english-local-under-5b', table)
    for component in components:
        if component['type'] == 'dataframe':
            value = component['props'].get('value')
            if isinstance(value, dict) and value.get('headers'):
                export_table(folder, f'table-{component["id"]}', value)
    metadata = {'source': BASE, 'retrieved_utc': stamp, 'filters': {'max_parameters_billion': args.max_size, 'proprietary': False},
                'request': data, 'api': dependency['api_name'], 'rows': len(rows),
                'limits': ['RTFx is publisher throughput on its hardware/batch/runtime; not local AMD latency or VRAM.',
                           'English aggregate is not multilingual quality; exported multilingual tables retain their own coverage.']}
    (folder / 'provenance.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(folder), 'rows': len(rows), 'top_20': rows[:20]}, ensure_ascii=True))


if __name__ == '__main__':
    main()
