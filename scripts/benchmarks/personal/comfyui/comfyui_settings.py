"""User-run ComfyUI setting screens; original VAE and current saved defaults stay intact."""

import argparse
import json
import subprocess
import sys

from scripts.benchmarks.shared.paths import BenchmarkPaths
from scripts.benchmarks.shared.reporting import report_run
from scripts.config import project_config as project_cfg
from scripts.shared.timing import timed


def setting_cases(group: str) -> list[tuple[str, list[str]]]:
    if group == "scaling":
        return [
            (
                f"{workload}-spatial-{size}-{overlap}",
                [*options, "--spatial-tile", str(size), "--spatial-overlap", str(overlap)],
            )
            for workload, options in (("higher-res", ["--resolution", "640"]), ("longer-clip", ["--seconds", "10"]))
            for size, overlap in ((512, 64), (1024, 256))
        ]
    if group == "focused":
        return [
            ("baseline", []),
            ("dynamic-off", ["--launch-case", "dynamic-off"]),
            ("spatial-1024-256", ["--spatial-tile", "1024", "--spatial-overlap", "256"]),
        ]
    if group == "stability":
        return [
            ("monitor-on-a", []),
            ("monitor-off-a", ["--no-vram-monitor"]),
            ("monitor-off-b", ["--no-vram-monitor"]),
            ("monitor-on-b", []),
        ]
    if group == "flags":
        return [
            (case, ["--launch-case", case])
            for case in ("baseline", "smart-on", "autotune-off", "triton-on", "dynamic-off", "pinned-on", "baseline")
        ]
    if group == "spatial":
        return [
            (f"spatial-{size}-{overlap}", ["--spatial-tile", str(size), "--spatial-overlap", str(overlap)])
            for size, overlap in ((512, 64), (768, 192), (1024, 256), (512, 64))
        ]
    if group == "temporal":
        return [
            (
                f"temporal-{size}-{overlap}",
                ["--seconds", "10", "--temporal-tile", str(size), "--temporal-overlap", str(overlap)],
            )
            for size, overlap in ((128, 32), (64, 16), (192, 48), (128, 32))
        ]
    raise ValueError(f"Unknown group: {group}")


def commands(group: str, repeat: int, reverse: bool, dry_run: bool) -> list[tuple[str, list[str]]]:
    common = [
        sys.executable,
        "-m",
        "scripts.benchmarks.personal.comfyui.comfyui_video",
        "--workflow",
        str(project_cfg.CONFIG_DIR / "comfyui/workflows/video_ltx2_5_i2v_default.json"),
        "--preset",
        "user",
        "--model",
        "1",
        "--encoder",
        "1",
        "--repeat",
        str(repeat),
        "--mode",
        "2",
        "--seconds",
        "5",
        "--fps",
        "24",
        "--resolution",
        "480",
        "--video-vae",
        "diffusion",
        "--vae-decode",
        "tiled",
        "--spatial-tile",
        "512",
        "--spatial-overlap",
        "64",
        "--temporal-tile",
        "128",
        "--temporal-overlap",
        "32",
    ]
    if group != "flags":
        common += ["--launch-case", "baseline"]
    if dry_run:
        common.append("--dry-run")
    cases = setting_cases(group)
    if reverse:
        cases.reverse()
    # argparse uses the final occurrence when a case overrides a shared value.
    return [(name, common + options) for name, options in cases]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "group",
        choices=("focused", "scaling", "stability", "flags", "spatial", "temporal"),
        nargs="?",
        default="stability",
    )
    parser.add_argument("--repeat", type=int, default=2, help="Clips per fresh server; default 2")
    parser.add_argument("--reverse", action="store_true", help="Reverse case order for a confirmation pass")
    parser.add_argument("--dry-run", action="store_true", help="Save commands and graphs without launching ComfyUI")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be positive")
    plan = commands(args.group, args.repeat, args.reverse, args.dry_run)
    paths = BenchmarkPaths(__file__).new_run()
    (paths.artifacts / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    with report_run(paths, "ComfyUI setting screen", "probes", settings=vars(args)) as report:
        print(f"[OUTPUT] {paths.root}", flush=True)
        print(f"[PLAN] {len(plan)} fresh servers; {len(plan) * args.repeat} clips; original VAE only", flush=True)
        for index, (name, command) in enumerate(plan, 1):
            print(f"[CASE] {index}/{len(plan)} {name}", flush=True)
            subprocess.run(command, cwd=project_cfg.BASE_DIR, check=True)
        if args.dry_run:
            report.status = "dry-run"


if __name__ == "__main__":
    with timed("ComfyUI setting screen"):
        main()
