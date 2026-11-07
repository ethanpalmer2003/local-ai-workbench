"""Normalized engine contract for comparable LLM inference measurements."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from scripts.benchmarks.shared.paths import RunPaths


@dataclass
class EngineOptions:
    builds: list[str] = field(default_factory=lambda: ["all"])
    profiles: list[str] = field(default_factory=lambda: ["swift15"])
    prompts: dict[str, str] = field(default_factory=dict)
    max_tokens: int = 128
    warmup_tokens: int = 32
    repeats: int = 3
    ctx_fill: int = 0
    startup_timeout: float = 180
    request_timeout: float = 300


@dataclass
class RunSpec:
    identifier: str
    model: str = ""
    quant: str = ""
    backend: str = ""
    build: str = ""
    profile: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    engine: str
    identifier: str
    model: str = ""
    quant: str = ""
    backend: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    reason: str = ""
    startup_seconds: float | None = None
    load_seconds: float | None = None
    warmup_seconds: float | None = None
    decode_tokens_per_second: float | None = None
    decode_scope: str = ""
    prefill_tokens_per_second: float | None = None
    vram_peak_mib: float | None = None
    request_samples: list[dict[str, Any]] = field(default_factory=list)
    log: str = ""


class EngineAdapter(Protocol):
    name: str
    label: str

    def runs(self, options: EngineOptions) -> list[RunSpec]: ...

    def available(self, spec: RunSpec) -> tuple[bool, str]: ...

    def run(self, spec: RunSpec, options: EngineOptions, output: RunPaths) -> EngineResult: ...


def skipped(engine: str, spec: RunSpec, reason: str) -> EngineResult:
    return EngineResult(
        engine=engine,
        identifier=spec.identifier,
        model=spec.model,
        quant=spec.quant,
        backend=spec.backend,
        settings=spec.settings,
        status="skipped",
        reason=reason,
    )


def failed(engine: str, spec: RunSpec, error: Exception) -> EngineResult:
    return EngineResult(
        engine=engine,
        identifier=spec.identifier,
        model=spec.model,
        quant=spec.quant,
        backend=spec.backend,
        settings=spec.settings,
        status="failed",
        reason=str(error),
    )
