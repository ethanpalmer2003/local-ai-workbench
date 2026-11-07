"""Console timing for benchmark setup, cleanup and whole-run diagnostics."""

import time
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def timed(label: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        print(f"[TIME] {label}: {time.perf_counter() - started:.3f}s", flush=True)
