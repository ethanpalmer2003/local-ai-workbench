"""Expected wall-clock ranges for the standard long runs, in seconds.

Measured on this machine with warm caches and nothing skipped. `stage_runner` uses `typical` for the
bar estimate and reports a stage that ends above `high` as slow. A skipped live suite finishes far
below `low`, which is normal and not reported.
"""

RANGES: dict[str, tuple[int, int, int]] = {
    "frameworks": (15, 35, 300),
    "models": (10, 30, 120),
    "gate": (45, 55, 80),
    "suite": (20, 45, 80),
    "launchers": (70, 110, 200),
    "backends": (90, 150, 280),
}


def typical(stage: str) -> float:
    return float(RANGES[stage][1])


def high(stage: str) -> int:
    return RANGES[stage][2]
