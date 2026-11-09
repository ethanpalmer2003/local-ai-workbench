"""Expected wall-clock ranges for one full validation run, in seconds.

Measured on this machine with warm caches and nothing skipped. The progress runner uses `typical` for
its estimate and reports a stage that ends above `high` as slow. Skipped live suites finish far below
`low`, which is normal and not reported.
"""

RANGES: dict[str, tuple[int, int, int]] = {
    "frameworks": (15, 35, 300),
    "gate": (45, 55, 80),
    "suite": (18, 28, 50),
    "launchers": (240, 275, 380),
    "backends": (230, 260, 360),
}


def typical(stage: str) -> float:
    return float(RANGES[stage][1])


def high(stage: str) -> int:
    return RANGES[stage][2]


def classify(stage: str, seconds: float) -> str:
    """`slow` when a stage outran its range, otherwise `ok`."""
    return "slow" if seconds > high(stage) else "ok"
