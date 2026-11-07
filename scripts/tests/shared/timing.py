import time
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def timed(label: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        print(f"[TIME] {label}: {time.perf_counter() - started:.3f}s", flush=True)


class TimedTextTestResult(unittest.TextTestResult):
    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.test_started = 0.0
        self.case_seconds: dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.test_started = time.perf_counter()

    def stopTest(self, test: unittest.TestCase) -> None:
        elapsed = round(time.perf_counter() - self.test_started, 3)
        self.case_seconds[test.id()] = elapsed
        self.stream.write(f"[TIME] {test.id()}: {elapsed:.3f}s\n")
        super().stopTest(test)
