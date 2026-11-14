"""Identity checks for reused proxy/native benchmark services, without stopping them."""

import hashlib
import json
import urllib.request
from typing import Any

from scripts.launchers import launch_util


def audio_model_token(config: dict[str, Any]) -> str:
    """Generation/tone defaults may change without replacing the loaded model."""
    selected = {key: config.get(key) for key in ("model", "selected_model", "server_session_options")}
    if not selected["selected_model"]:
        raise RuntimeError("Audio service did not identify its selected model")
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def endpoint_identity(port: int, model: str) -> str:
    import psutil

    pids = launch_util.listening_process_ids(port)
    return f"{model}:{sorted((pid, psutil.Process(pid).create_time()) for pid in pids)}" if pids else ""


def audio_identity() -> str:
    import psutil

    from scripts.launchers import launcher_config as cfg

    identities = []
    for port in (cfg.AUDIOCPP_SERVICE.port, cfg.AUDIOCPP_SERVICE.internal_port):
        pids = launch_util.listening_process_ids(port)
        if not pids:
            return ""
        identities.extend((pid, psutil.Process(pid).create_time()) for pid in pids)
    with urllib.request.urlopen(f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/proxy/config", timeout=5) as response:
        config = json.load(response)
    digest = audio_model_token(config)
    return f"{sorted(identities)}:{digest}"
