"""Explicit AudioCpp model residency on an owned, lazily started server."""

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from scripts.config import project_config as project_cfg
from scripts.launchers.audiocpp.kokoro import audio_environment
from scripts.launchers.shared.services import native
from scripts.launchers.shared.services.process import http_ready


def start(config: dict[str, Any], port: int):
    config: dict[str, Any] = {**config, 'host': '127.0.0.1', 'port': port, 'lazy_load': True,
              'ui_management': True, 'max_loaded_models': 2, 'idle_unload_ms': 0}
    text = json.dumps(config, indent=2)
    file = project_cfg.component('audiocpp').generated_dir / f'practice-managed-{hashlib.sha256(text.encode()).hexdigest()[:12]}.json'
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding='utf-8')
    command = [str(project_cfg.AUDIOCPP_SERVER_EXE), '--config', str(file), '--no-ui']
    return native.start_server(command, [project_cfg.AUDIOCPP_SERVER_EXE, *(Path(row['path']) for row in config['models'])],
                               port, 'Practice AudioCpp', lambda: http_ready(f'http://127.0.0.1:{port}/health'),
                               lambda: native.matches(command), env=audio_environment(), component_key='audiocpp')


def post(url: str, action: str, model: dict[str, Any]):
    request = urllib.request.Request(url + '/v1/models/' + action, json.dumps(model).encode(),
                                     {'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())
