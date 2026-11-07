"""Reusable adapter setup; assertions and expected policies stay in each test."""

from contextlib import contextmanager, ExitStack
from collections.abc import Iterator
from dataclasses import dataclass, replace, fields as dataclass_fields
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.shared.services import native
from scripts.tests.shared.process_fixtures import running_process


@dataclass
class StartupHarness:
    adapter: Any
    worker: MagicMock
    launch: MagicMock
    stop: MagicMock
    ready: MagicMock
    matching: MagicMock
    occupied: MagicMock


@contextmanager
def startup_fixture(adapter: Any, settings_key: str, root: Path) -> Iterator[StartupHarness]:
    root = root / settings_key
    root.mkdir(parents=True, exist_ok=True)
    current = getattr(cfg, settings_key)
    files = {key: root / (key + ".fixture") for key in ("exe", "model", "mmproj") if hasattr(current, key)}
    for path in files.values():
        path.touch()
    worker = running_process()
    with ExitStack() as stack:
        init_fields = {field.name for field in dataclass_fields(current) if field.init}
        overrides = {key: path for key, path in files.items() if key in init_fields}
        stack.enter_context(patch.object(cfg, settings_key, replace(current, **overrides)))
        for key, path in files.items():
            if key not in init_fields:
                stack.enter_context(patch.object(type(current), key, PropertyMock(return_value=path)))
        stack.enter_context(patch.object(project_cfg, "LOGS_DIR", root))
        stack.enter_context(patch.object(native.launch_util, "llama_server_running", return_value=False))
        launch = stack.enter_context(patch.object(native.launch_util, "launch_process", return_value=worker))
        stop = stack.enter_context(patch.object(native.launch_util, "kill_process_tree"))
        occupied = stack.enter_context(patch.object(native.launch_util, "port_listening", return_value=False))
        ready = stack.enter_context(patch.object(adapter, "ready", side_effect=[False, True]))
        matching = stack.enter_context(patch.object(adapter, "matching_server", return_value=True))
        yield StartupHarness(adapter, worker, launch, stop, ready, matching, occupied)
