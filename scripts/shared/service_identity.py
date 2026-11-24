"""Identity checks for reused proxy/native benchmark services, without stopping them."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

import psutil
import requests

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg


def audio_model_token(config: dict[str, Any]) -> str:
    """Generation/tone defaults may change without replacing the loaded model."""
    selected = {key: config.get(key) for key in ("model", "selected_model", "server_session_options")}
    if not selected["selected_model"]:
        raise RuntimeError("Audio service did not identify its selected model")
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def _process_identities(pids: Iterable[int]) -> list[tuple[int, float]]:
    """Each listening pid with its start time; one that exits mid-check is left out, not guessed."""
    pairs: list[tuple[int, float]] = []
    for pid in sorted(pids):
        try:
            pairs.append((pid, psutil.Process(pid).create_time()))
        except (psutil.Error, OSError):
            continue
    return pairs


def endpoint_identity(port: int, model: str) -> str:
    identities = _process_identities(launch_util.listening_process_ids(port))
    return f"{model}:{identities}" if identities else ""


def audio_identity() -> str:

    identities: list[tuple[int, float]] = []
    for port in (cfg.AUDIOCPP_SERVICE.port, cfg.AUDIOCPP_SERVICE.internal_port):
        found = _process_identities(launch_util.listening_process_ids(port))
        if not found:
            return ""
        identities.extend(found)
    response = requests.get(f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/proxy/config", timeout=5)
    response.raise_for_status()
    config = response.json()
    digest = audio_model_token(config)
    return f"{sorted(identities)}:{digest}"
