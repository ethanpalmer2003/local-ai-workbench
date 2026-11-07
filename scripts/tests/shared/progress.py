"""Plain-text progress bars for live targets and the model-free suite."""

import sys
from typing import Any, TextIO

from scripts.tests.shared.timing import TimedTextTestResult


class ProgressBar:
    def __init__(
        self,
        total: int,
        label: str,
        *,
        stream: TextIO | None = None,
        width: int = 20,
        step: int | None = None,
    ) -> None:
        self.total = max(int(total), 1)
        self.label = label
        self.stream = stream or sys.stdout
        self.width = width
        self.step = step or max(1, self.total // 20)
        self.current = 0
        self.last_reported = 0

    def update(self, name: str = "") -> None:
        self.current += 1
        if self.current != self.total and self.current - self.last_reported < self.step:
            return
        self.last_reported = self.current
        filled = int(self.width * self.current / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        suffix = f" {name}" if name else ""
        print(
            f"[PROGRESS] {self.label} [{bar}] {self.current}/{self.total}{suffix}",
            file=self.stream,
            flush=True,
        )


class ProgressTextTestResult(TimedTextTestResult):
    """Model-free result that adds a periodic bar without replacing verbose output."""

    progress_total = 0
    progress_label = "tests"

    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.progress = ProgressBar(self.progress_total, self.progress_label, stream=stream)

    def stopTest(self, test: "Any") -> None:
        super().stopTest(test)
        self.progress.update(test.id())
