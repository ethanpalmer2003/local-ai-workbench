"""Run bounded native smoke probes sequentially, preserving failures and owned-process cleanup."""

import argparse
import os
import subprocess
import sys
import time

from scripts.benchmarks.shared import provenance
from scripts.benchmarks.shared.reporting import RunReport
from scripts.config import project_config as project_cfg
from scripts.launchers import launch_util
from scripts.launchers.runtime.execution_context import require_native_execution
from scripts.tests.shared import live_stamp
from scripts.tests.shared.paths import CasePaths
from scripts.tests.shared.progress import ProgressBar

PROBES = {
    "parakeet": ("scripts.tests.cases.asr.parakeetcpp.smoke", [], 240),
    "whisper": (
        "scripts.benchmarks.asr.whisper_embedded_compare",
        ["--order", "internal", "vulkan-fa", "--repetitions", "1", "--budget", "180"],
        240,
    ),
    "practice-whisper": ("scripts.tests.cases.asr.shared.language_practice_whisper", [], 240),
    "practice-qwen": (
        "scripts.tests.cases.asr.shared.language_practice_whisper",
        ["--transcription-engine", "qwen3-asr"],
        240,
    ),
    "gemma": ("scripts.benchmarks.asr.gemma_audio_compare", [], 300),
    "kokoro": ("scripts.tests.cases.koboldcpp.kobold_embedded_compare", ["--kind", "tts"], 300),
    "images": ("scripts.tests.cases.koboldcpp.kobold_embedded_compare", ["--kind", "image"], 300),
    "ming3-tts": ("scripts.tests.cases.audiocpp.audiocpp_backend_compare", ["--case", "ming3-tts"], 180),
}


def run_probes(names: list[str]) -> bool:
    from scripts.tests.shared.native_suites import native_policy, refuse_existing_sessions

    if live_stamp.unchanged("backends", names):
        print(
            f"[SKIP] backends: sources unchanged since the last pass ({', '.join(names)}); "
            "set AI_LIVE_FORCE=1 to rerun",
            flush=True,
        )
        return True
    context = dict(require_native_execution("Quick native validation"))
    with native_policy():
        launch_util.assign_current_process_to_job()
        refuse_existing_sessions()
        passed = _run_probes(names, context)
    if passed:
        live_stamp.record("backends", names)
    return passed


PROBE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "parakeet": ("asr/parakeetcpp",),
    "whisper": ("asr/whispercpp",),
    "practice-whisper": ("asr/whispercpp", "audiocpp"),
    "practice-qwen": ("asr/llamacpp", "audiocpp"),
    "gemma": ("asr/llamacpp", "audiocpp"),
    "kokoro": ("koboldcpp", "audiocpp"),
    "images": ("koboldcpp", "sdcpp"),
    "ming3-tts": ("audiocpp",),
}


def _run_probes(names: list[str], context: dict[str, object]) -> bool:
    run = CasePaths(__file__).new_run()
    print(f"[OUTPUT] {run.root}", flush=True)
    report = RunReport("native/backends", "native-backends")
    report.settings["execution_context"] = context
    report.record_provenance(
        models=[],
        frameworks=[
            provenance.framework_state(key) for key in sorted({key for name in names for key in PROBE_COMPONENTS[name]})
        ],
    )
    report.save(run)
    results = []
    progress = ProgressBar(len(names), "backends")
    console_title = os.environ.get("AI_TEST_TITLE", "Live Backends")
    launch_util.set_console_title(console_title)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    for name in names:
        module, arguments, timeout = PROBES[name]
        command = [sys.executable, "-m", module, *arguments]
        tick = time.monotonic()
        progress.update(name)
        print(f"[START] {name}", flush=True)
        error = None
        with (run.logs / f"{name}.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=project_cfg.BASE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
            launch_util.assign_process_to_job(process.pid)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                error, code = f"Whole-probe budget {timeout}s exhausted", 124
            finally:
                if process.poll() is None:
                    launch_util.kill_process_tree(process.pid)
                    process.wait(timeout=15)
        results.append(
            {
                "target": name,
                "kind": "backend",
                "status": "completed" if code == 0 else "failed",
                "command": command,
                "exit_code": code,
                "reason": error or "",
                "seconds": time.monotonic() - tick,
                "log": str(run.logs / f"{name}.log"),
            }
        )
        report.results = results
        report.save(run)
        print(f"[{'OK' if code == 0 else 'FAIL'}] {name}: {results[-1]['seconds']:.1f}s; exit={code}", flush=True)
        launch_util.set_console_title(console_title)
    passed = all(result["exit_code"] == 0 for result in results)
    report.status = "completed" if passed else "failed"
    report.results = results
    report.save(run)
    launch_util.set_console_title(console_title)
    print(f"[RESULTS] {run.artifacts}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="+",
        choices=tuple(PROBES),
        default=list(PROBES),
        help="Narrow the run to specific probes (default: every probe)",
    )
    args = parser.parse_args()
    return 0 if run_probes(args.only) else 1


if __name__ == "__main__":
    raise SystemExit(main())
