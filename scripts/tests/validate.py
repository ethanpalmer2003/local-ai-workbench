"""Run the full validation stack in one progress bar, after bringing frameworks up to date.

Frameworks update first so the checks and live stages describe the state the machine is actually in;
`--models` adds a read-only source check for the catalog. The model-free gate and suite follow, then
both live suites, which skip themselves when their sources and installations are unchanged. Expected
ranges live in `scripts/config/shared/stage_times.py`.
"""

import argparse
import os
from dataclasses import replace

from scripts.config import project_config as project_cfg
from scripts.config.shared import stage_times
from scripts.shared import consent, staleness
from scripts.shared.file_sets import maintained_files
from scripts.tests.shared import live_stamp
from scripts.tools import stage_runner

MODULES: dict[str, tuple[str, tuple[str, ...]]] = {
    # - ComfyUI is vendor-managed and updated by hand, so it stays out of the automatic preflight
    "frameworks": ("scripts.download.frameworks.update_frameworks", ("--skip-comfyui", "--yes")),
    "models": ("scripts.download.models.updates", ()),
    "gate": ("scripts.review", ("--all", "--manual")),
    "suite": ("scripts.tests.run", ("--all", "--manual")),
    "launchers": ("scripts.tests.cases.suites.live_frameworks", ("--yes",)),
    "backends": ("scripts.tests.cases.suites.quick_validation", ("--yes",)),
}
ALL_KEYS = ("frameworks", "models", "gate", "suite", "launchers", "backends")
DEFAULT_KEYS = tuple(key for key in ALL_KEYS if key != "models")


def stage_fingerprints() -> dict[str, str]:
    """What each stage reads, hashed: a stage whose digest still matches is skipped.

    The gate reads every maintained file, the suite reads the Python ones, the preflights read the updater
    and config trees, and both live suites read what `live_stamp` already hashes. Documentation therefore
    invalidates only the gate.
    """
    files = maintained_files()
    python = [path for path in files if path.suffix == ".py"]
    updaters = [
        path
        for path in files
        if path.is_relative_to(project_cfg.SCRIPTS_DIR / "download") or path.is_relative_to(project_cfg.CONFIG_DIR)
    ]
    digests = {
        "frameworks": staleness.fingerprint(updaters, project_cfg.BASE_DIR),
        "models": staleness.fingerprint([path for path in updaters if path.suffix == ".py"], project_cfg.BASE_DIR),
        "gate": staleness.fingerprint(files, project_cfg.BASE_DIR),
        "suite": staleness.fingerprint(python, project_cfg.BASE_DIR),
    }
    live = live_stamp.fingerprint()
    digests["launchers"] = live
    digests["backends"] = live
    return digests


def _stage(key: str, fingerprints: dict[str, str]) -> stage_runner.Stage:
    module, arguments = MODULES[key]
    _, typical, high = stage_times.RANGES[key]
    # - update stages keep every line; the checks and live suites keep their tagged summaries
    return stage_runner.Stage(
        key=key,
        module=module,
        arguments=arguments,
        typical=typical,
        high=high,
        stream=key in ("frameworks", "models"),
        fingerprint=fingerprints[key],
    )


def plan(
    only: list[str] | None = None, models: bool = False, build: str | None = None
) -> tuple[stage_runner.Stage, ...]:
    """The stages for this run, in execution order; `only` narrows, `models` adds the source check.

    `build` names a parked build the framework preflight should rebuild, so one validation can produce a
    fresh binary instead of the build staying hand-run.
    """
    keys = list(only) if only else [key for key in ALL_KEYS if models or key in DEFAULT_KEYS]
    fingerprints = stage_fingerprints()
    stages = []
    for key in keys:
        stage = _stage(key, fingerprints)
        if key == "frameworks" and build:
            stage = replace(stage, arguments=(*stage.arguments, "--build", build))
        stages.append(stage)
    return tuple(stages)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=list(ALL_KEYS), help="run only these stages")
    parser.add_argument("--models", action="store_true", help="also check catalog sources against the Hub")
    parser.add_argument("--force", action="store_true", help="rerun live suites even when they are unchanged")
    parser.add_argument("--no-update", action="store_true", help="skip the framework update preflight")
    parser.add_argument("--build", choices=("rdna",), help="rebuild this parked build in the frameworks stage")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and expected ranges")
    parser.add_argument("--verbose", action="store_true", help="stream every child line instead of the tagged ones")
    consent.flag(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    if args.force:
        os.environ["AI_LIVE_FORCE"] = "1"
    selected = list(args.only) if args.only else None
    if args.no_update:
        # - an explicit `--only frameworks` with `--no-update` names nothing to run; say that instead of
        #   falling back to the default plan, which would quietly run every other stage
        wanted = selected if selected is not None else list(ALL_KEYS)
        selected = [key for key in wanted if key != "frameworks"]
        if not selected:
            print("[FAIL] --no-update leaves no stage to run")
            return 1
    stages = plan(selected, args.models, args.build)
    if args.dry_run:
        print("Full validation plan; frameworks update first and live stages skip when unchanged:")
        for stage in stages:
            print(f"  {stage.key:<12} {stage.typical:>4.0f} s typical, {stage.high:>4.0f} s expected  {stage.module}")
        print(
            f"  {'total':<12} {sum(stage.typical for stage in stages):>4.0f} s when nothing is skipped and nothing updates"
        )
        return 0
    if not consent.ask("Full validation", sum(stage.typical for stage in stages), args.yes):
        return 1
    # - the preflight updated the frameworks, so the model and install checks are the point of this run
    os.environ["AI_MODEL_CHECKS"] = "1"
    results = stage_runner.run(
        stages,
        title="validate",
        stream=args.verbose,
        # - a stage that installs or updates what a later stage reads records the state it left behind
        fingerprint_after=lambda key: stage_fingerprints()[key],
    )
    return 0 if all(result.status != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
