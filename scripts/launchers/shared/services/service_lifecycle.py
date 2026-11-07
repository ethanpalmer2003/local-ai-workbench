"""On-demand service ownership, model residency and phase timing; no framework policy."""

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from scripts.launchers.shared.services.process import stop_owned


@dataclass
class Service:
    start: Callable[[], Any]
    load: Callable[[str], None] | None = None
    unload: Callable[[str], None] | None = None
    process: Any = None
    external: bool = False
    residents: set[str] = field(default_factory=set)


class ServiceLifecycle:
    def __init__(
        self,
        services: dict[str, Service],
        groups: dict[str, str],
        sink=lambda event: None,
        models: dict[str, str] | None = None,
    ):
        self.services, self.groups, self.sink = services, groups, sink
        self.models = dict(models or {})
        self.lock = threading.RLock()
        self.events: list[dict[str, Any]] = []
        self.active = 0
        self.states = dict.fromkeys(groups, "unloaded")

    def event(self, stage: str, phase: str, started: float, **fields):
        service = self.services[self.groups[stage]]
        event = dict(
            id=len(self.events) + 1,
            timestamp=time.time(),
            stage=stage,
            phase=phase,
            model=self.models.get(stage),
            group=self.groups[stage],
            pid=getattr(service.process, "pid", None),
            owned=not service.external,
            duration_ms=(time.perf_counter() - started) * 1000,
            **fields,
        )
        self.events.append(event)
        self.sink(event)

    def ensure(self, stage: str):
        with self.lock:
            service = self.services[self.groups[stage]]
            if service.process is not None and service.process.poll() is not None:
                service.process = None
                service.residents.clear()
            if stage in service.residents:
                return
            started = time.perf_counter()
            self.states[stage] = "loading"
            try:
                if service.process is None and not service.external:
                    service.process = service.start()
                    service.external = service.process is None
                    self.event(
                        stage,
                        "startup_ready",
                        started,
                        reused=service.external,
                        includes_model_load=service.load is None,
                        model_load_ms=None,
                    )
                if service.load and not service.external:
                    loading = time.perf_counter()
                    service.load(stage)
                    self.event(stage, "model_load", loading)
                service.residents.add(stage)
                self.states[stage] = "external" if service.external else "loaded"
            except Exception as error:
                self.states[stage] = "failed"
                self.event(stage, "load_failed", started, error=str(error))
                raise

    @contextmanager
    def use(self, stage: str | None, phase: str = "request"):
        if stage is None:
            yield
            return
        with self.lock:
            self.ensure(stage)
            self.active += 1
        started = time.perf_counter()
        outcome = "failed"
        try:
            yield
            outcome = "complete"
        finally:
            with self.lock:
                self.active -= 1
                self.event(stage, phase, started, outcome=outcome, excludes_startup=True)

    def release(self, stage: str):
        with self.lock:
            if self.active:
                raise RuntimeError("A model request is active; stop capture or wait before unloading")
            service = self.services[self.groups[stage]]
            if service.external:
                raise RuntimeError("This service is reused and not owned by this workspace; it was retained")
            started = time.perf_counter()
            if stage in service.residents and service.unload:
                service.unload(stage)
            service.residents.discard(stage)
            self.states[stage] = "shared resident" if service.residents and not service.unload else "unloaded"
            if not service.residents and service.process is not None:
                stop_owned(service.process)
                service.process = None
                for other, group in self.groups.items():
                    if group == self.groups[stage]:
                        self.states[other] = "unloaded"
            self.event(stage, "unload", started)

    def snapshot(self):
        with self.lock:
            return {
                "stages": {
                    stage: {
                        "state": state,
                        "group": self.groups[stage],
                        "pid": getattr(self.services[self.groups[stage]].process, "pid", None),
                        "owned": not self.services[self.groups[stage]].external,
                    }
                    for stage, state in self.states.items()
                },
                "events": self.events[-100:],
            }

    def close(self):
        for service in self.services.values():
            if service.process is not None:
                stop_owned(service.process)
                service.process = None
