"""Check catalog sources, then fetch missing active files, behind one progress bar."""

import sys

from scripts.tools import stage_runner, stage_times

SOURCES = "models"
DOWNLOADS = "model-downloads"


def _bounds(key: str) -> tuple[float, float]:
    _, typical, high = stage_times.RANGES[key]
    return float(typical), float(high)


def plan(arguments: tuple[str, ...] = ()) -> tuple[stage_runner.Stage, ...]:
    """The check first, then only the active files that are not installed yet."""
    typical, high = _bounds(SOURCES)
    download_typical, download_high = _bounds(DOWNLOADS)
    return (
        stage_runner.Stage(
            key=SOURCES, module="scripts.download.models.updates", typical=typical, high=high, arguments=arguments
        ),
        stage_runner.Stage(
            key=DOWNLOADS,
            module="scripts.download.models.download_catalog",
            typical=download_typical,
            high=download_high,
            arguments=("--active", "--download"),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    results = stage_runner.run(plan(arguments), title="models", stream=True)
    return 0 if all(result.status != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
