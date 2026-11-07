"""Domain-neutral benchmark lifecycle: setup and warmup never enter request timing."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import statistics
import math
import time
from typing import Any, TypeVar

T = TypeVar("T")
# One timing owner for every domain; adapters must not estimate/subtract hidden loading costs.


def measure_cold_process(operation: Callable[[], T]) -> tuple[T, dict[str, Any]]:
    """A whole-process diagnostic has no observable startup/load/inference split."""
    started = time.perf_counter()
    value = operation()
    return value, {
        "timing_scope": "cold_process_diagnostic",
        "status": "completed",
        "process_seconds": time.perf_counter() - started,
        "startup_seconds": None,
        "model_load_seconds": None,
        "request_seconds": None,
        "phase_observability": "Process API exposes no loading/inference boundary",
    }


@contextmanager
def workflow_timing() -> Iterator[dict[str, Any]]:
    """Wall time when a pipeline can reload/offload models inside its execution."""
    row: dict[str, Any] = {
        "timing_scope": "workflow_total_including_dynamic_loading",
        "status": "completed",
        "model_load_seconds": None,
        "request_seconds": None,
    }
    started = time.perf_counter()
    try:
        yield row
    except BaseException:
        row["status"] = "failed"
        raise
    finally:
        row["workflow_seconds"] = time.perf_counter() - started


class BenchmarkContractError(RuntimeError):
    pass


@dataclass
class RequestTiming:
    clock: Callable[[], float]
    started: float
    seconds: float | None = None
    status: str = "running"
    marks: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    def reject(self, reason: str) -> None:
        self.status, self.error = "failed", reason

    def mark(self, name: str) -> None:
        if self.status != "running":
            raise BenchmarkContractError("Cannot mark a finished request")
        self.marks.setdefault(name, self.clock() - self.started)

    def record(self) -> dict[str, Any]:
        return {
            "timing_scope": "resident_request",
            "request_seconds": self.seconds,
            "status": self.status,
            "marks_seconds": dict(self.marks),
            "error": self.error,
        }


class BenchmarkLifecycle:
    """Adapters own model/process details; the lifecycle owns timing and eligibility."""

    def __init__(
        self,
        identity: Callable[[], str],
        cleanup: Callable[[], None] = lambda: None,
        *,
        resident: bool = True,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.identity = identity
        self.cleanup = cleanup
        self.resident = resident
        self.clock = clock
        self.state = "new"
        self.prepared_identity: str | None = None
        self.phases: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.active_request = False

    def _phase(self, name: str, operation: Callable[[], T]) -> T:
        started = self.clock()
        status = "completed"
        try:
            return operation()
        except BaseException as error:
            status = "failed"
            self.state = "failed"
            self.errors.append(f"{name}: {error}")
            raise
        finally:
            self.phases.append({"phase": name, "seconds": self.clock() - started, "status": status})

    def prepare(
        self,
        startup: Callable[[], Any],
        load: Callable[[], Any] | None = None,
        *,
        combined: bool = False,
        reused: bool = False,
        load_includes_inference: bool = False,
    ) -> None:
        if self.state != "new" or (combined and load is not None):
            raise BenchmarkContractError("Invalid or repeated preparation")
        self._phase("reuse_verification" if reused else "startup_and_model_load" if combined else "startup", startup)
        if load is not None:
            self._phase("model_load_and_first_inference" if load_includes_inference else "model_load", load)
        self.prepared_identity = self.identity()
        if not self.prepared_identity:
            self.state = "failed"
            raise BenchmarkContractError("Adapter must identify its loaded process/model instance")
        self.state = "ready"

    def _check_identity(self) -> None:
        if self.identity() != self.prepared_identity:
            self.state = "failed"
            raise BenchmarkContractError("Process/model identity changed; setup must be repeated outside measurement")

    def adopt_prepared(self, seconds: float, *, combined: bool = True, acquisition: bool = False) -> None:
        """Import an existing runner's observed setup interval, never subtract an estimate."""
        if self.state != "new" or seconds < 0:
            raise BenchmarkContractError("Invalid observed preparation")
        self.prepared_identity = self.identity()
        if not self.prepared_identity:
            raise BenchmarkContractError("Prepared backend must have a live model/process identity")
        self.phases.append(
            {
                "phase": "session_acquisition" if acquisition else "startup_and_model_load" if combined else "startup",
                "seconds": seconds,
                "status": "completed",
            }
        )
        self.state = "ready"

    def warmup(self, operation: Callable[[], Any], *, repeats: int = 1, includes_model_load: bool = False) -> None:
        if self.state not in ("ready", "warm") or repeats < 1:
            raise BenchmarkContractError("Warmup requires a prepared backend and at least one request")
        self._check_identity()
        for _ in range(repeats):
            self._phase("model_load_and_first_inference" if includes_model_load else "warmup", operation)
            self._check_identity()
        self.state = "warm"

    @contextmanager
    def request(self) -> Iterator[RequestTiming]:
        if not self.resident or self.state != "warm" or self.active_request:
            raise BenchmarkContractError(
                "Performance requests require a resident, warmed backend and no active request"
            )
        self._check_identity()
        timing = RequestTiming(self.clock, self.clock())
        self.active_request = True
        finished = timing.started
        try:
            try:
                yield timing
            finally:
                finished = self.clock()
            self._check_identity()
            if timing.status == "running":
                timing.status = "completed"
        except BaseException as error:
            timing.status = "failed"
            self.errors.append(f"request: {error}")
            raise
        finally:
            timing.seconds = finished - timing.started
            self.active_request = False
            self.requests.append(timing.record())

    def measure(
        self, operation: Callable[[], T], *, accept: Callable[[T], bool] | None = None
    ) -> tuple[T, dict[str, Any]]:
        with self.request() as timing:
            value = operation()
            if accept is not None and not accept(value):
                timing.reject("Backend result rejected by adapter")
        return value, timing.record()

    def fork(self) -> "BenchmarkLifecycle":
        """Independent request recorder for concurrent calls to this warmed session."""
        if self.state != "warm" or not self.resident:
            raise BenchmarkContractError("Only a warmed resident session can supply request recorders")
        self._check_identity()
        child = BenchmarkLifecycle(self.identity, resident=True, clock=self.clock)
        child.prepared_identity = self.prepared_identity
        child.state = "warm"
        return child

    def record(self) -> dict[str, Any]:
        durations = {row["phase"]: row["seconds"] for row in self.phases}
        return {
            "schema": "benchmark-lifecycle-v1",
            "state": self.state,
            "resident": self.resident,
            "identity": self.prepared_identity,
            "startup_seconds": durations.get("startup"),
            "model_load_seconds": durations.get("model_load"),
            "startup_and_model_load_seconds": durations.get("startup_and_model_load"),
            "session_acquisition_seconds": durations.get("session_acquisition"),
            "model_load_and_first_inference_seconds": durations.get("model_load_and_first_inference"),
            "warmup_seconds": sum(row["seconds"] for row in self.phases if row["phase"] == "warmup"),
            "phases": list(self.phases),
            "requests": list(self.requests),
            "errors": list(self.errors),
        }

    def close(self) -> None:
        if self.active_request:
            raise BenchmarkContractError("Cannot close during an active request")
        if self.state != "closed":
            try:
                self._phase("cleanup", self.cleanup)
            finally:
                self.state = "closed"

    def __enter__(self) -> "BenchmarkLifecycle":
        return self

    def __exit__(self, kind, value, traceback) -> None:
        try:
            self.close()
        except BaseException as error:
            self.errors.append(str(error))
            if kind is None:
                raise


def summarize_requests(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row["request_seconds"]
        for row in rows
        if row.get("timing_scope") == "resident_request"
        and row.get("status") == "completed"
        and type(row.get("request_seconds")) in (int, float)
        and math.isfinite(row["request_seconds"])
        and row["request_seconds"] >= 0
    ]
    return {
        "timing_scope": "resident_request",
        "samples": len(eligible),
        "excluded_rows": len(rows) - len(eligible),
        "p50_seconds": statistics.median(eligible) if eligible else None,
        "p95_seconds": statistics.quantiles(eligible, n=100, method="inclusive")[94] if len(eligible) >= 20 else None,
        "p95_minimum_samples": 20,
    }


def summarize_report(value: Any) -> dict[str, Any]:
    """Collect lifecycle records once; never promote arbitrary elapsed-time fields."""
    rows: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            lifecycle = item.get("benchmark", item)
            if isinstance(lifecycle, dict) and lifecycle.get("schema") == "benchmark-lifecycle-v1":
                rows.extend(lifecycle.get("requests", []))
                return
            if "timing_scope" in item or "request_seconds" in item:
                rows.append(item)
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return summarize_requests(rows)
