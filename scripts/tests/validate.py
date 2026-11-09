"""Run the full validation stack in one progress bar, after bringing frameworks up to date.

Frameworks update first so the checks and live stages describe the state the machine is actually in;
`--models` adds a read-only source check for the catalog. The model-free gate and suite follow, then
both live suites, which skip themselves when their sources and installations are unchanged. Expected
ranges live in `scripts/tests/shared/stage_times.py`.
"""

import argparse
import os

from scripts.tests.shared import stage_times
from scripts.tools import stage_runner

MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    # - ComfyUI is vendor-managed and updated by hand, so it stays out of the automatic preflight
    "frameworks": ("scripts.download.frameworks.update_frameworks", ("--skip-comfyui",)),
    "models": ("scripts.download.models.updates", ()),
    "gate": ("scripts.review", ()),
    "suite": ("scripts.tests.run", ()),
    "launchers": ("scripts.tests.cases.shared.live_frameworks", ()),
    "backends": ("scripts.tests.cases.shared.quick_validation", ()),
}
ALL_KEYS = ("frameworks", "models", "gate", "suite", "launchers", "backends")
DEFAULT_KEYS = tuple(key for key in ALL_KEYS if key != "models")


def _stage(key: str) -> stage_runner.Stage:
    module, arguments = MODULES[key]
    _, typical, high = stage_times.RANGES[key]
    return stage_runner.Stage(key=key, module=module, arguments=arguments, typical=typical, high=high)


def plan(only: list[str] | None = None, models: bool = False) -> tuple[stage_runner.Stage, ...]:
    """The stages for this run, in execution order; `only` narrows, `models` adds the source check."""
    keys = list(only) if only else [key for key in ALL_KEYS if models or key in DEFAULT_KEYS]
    return tuple(_stage(key) for key in keys)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=list(ALL_KEYS), help="run only these stages")
    parser.add_argument("--models", action="store_true", help="also check catalog sources against the Hub")
    parser.add_argument("--force", action="store_true", help="rerun live suites even when they are unchanged")
    parser.add_argument("--no-update", action="store_true", help="skip the framework update preflight")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and expected ranges")
    parser.add_argument("--verbose", action="store_true", help="stream every child line instead of the tagged ones")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.force:
        os.environ["AI_LIVE_FORCE"] = "1"
    selected = list(args.only) if args.only else None
    if args.no_update:
        selected = [key for key in (selected or ALL_KEYS) if key != "frameworks"]
    stages = plan(selected, args.models)
    if args.dry_run:
        print("Full validation plan; frameworks update first and live stages skip when unchanged:")
        for stage in stages:
            print(f"  {stage.key:<12} {stage.typical:>4.0f} s typical, {stage.high:>4.0f} s expected  {stage.module}")
        print(
            f"  {'total':<12} {sum(stage.typical for stage in stages):>4.0f} s when nothing is skipped and nothing updates"
        )
        return 0
    results = stage_runner.run(stages, title="validate", verbose=args.verbose)
    return 0 if all(result.status != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
