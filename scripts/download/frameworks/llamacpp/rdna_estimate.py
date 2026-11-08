import argparse
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from statistics import median

from .rdna_build import BUILD_DEFAULTS, RDNA_SOURCE

LINK_EXTS = (".exe", ".dll", ".lib", ".a", ".so", ".dylib")
OBJ_EXTS = (".obj", ".o")


def ninja_commands(build_dir: Path) -> list[str]:
    ninja = shutil.which("ninja")
    if not ninja:
        raise RuntimeError("ninja not found in PATH")

    result = subprocess.run([ninja, "-C", str(build_dir), "-n", "-v"], capture_output=True, text=True, check=True)

    return [re.sub(r"^\[\d+/\d+\]\s*", "", line.strip()) for line in result.stdout.splitlines() if line.strip()]


def command_kind(command: str) -> str | None:
    output = command_output(command)

    if not output:
        return None

    output = output.lower()

    if output.endswith((".obj", ".o")):
        return "compile"

    if output.endswith((".exe", ".dll", ".so", ".dylib")):
        return "link"

    if output.endswith((".lib", ".a")):
        return "archive"

    return None


def command_output(command: str) -> str | None:
    match = re.search(r'(?:^|\s)-o(?:\s+|=)(?:"([^"]+)"|(\S+))', command, re.I)
    if match:
        return match.group(1) or match.group(2)

    match = re.search(r'(?:^|\s)/Fo(?:"([^"]+)"|(\S+))', command, re.I)
    if match:
        return match.group(1) or match.group(2)

    return None


def _ninja_row(line: str) -> tuple[int, int, str, str] | None:
    if not line or line.startswith("#"):
        return None
    parts = line.split("\t")
    if len(parts) < 5:
        return None
    try:
        return int(parts[0]), int(parts[1]), parts[3], parts[4]
    except ValueError:
        return None


def _ninja_groups(log_path: Path) -> dict[tuple[int, int, str], set[str]]:
    groups: dict[tuple[int, int, str], set[str]] = defaultdict(set)
    for line in log_path.read_text(errors="replace").splitlines():
        parsed = _ninja_row(line)
        if parsed is not None:
            start, end, output, command = parsed
            groups[(start, end, command)].add(output)
    return groups


def _output_kind(outputs: set[str]) -> str | None:
    if any(output.lower().endswith(OBJ_EXTS) for output in outputs):
        return "compile"
    if any(output.lower().endswith(LINK_EXTS) for output in outputs):
        return "link"
    return None


def read_ninja_log(build_dir: Path) -> dict[str, list[tuple[str, float]]]:
    log_path = build_dir / ".ninja_log"
    if not log_path.exists():
        return {"compile": [], "link": []}

    result: dict[str, list[tuple[str, float]]] = {"compile": [], "link": []}
    for (start, end, _), outputs in _ninja_groups(log_path).items():
        seconds = (end - start) / 1000
        kind = _output_kind(outputs)
        if seconds <= 0 or kind is None:
            continue
        result[kind].extend(
            (output.replace("\\", "/"), seconds) for output in outputs if output.lower().endswith(OBJ_EXTS + LINK_EXTS)
        )
    return result


def sccache_stats() -> dict[str, int] | None:
    if not shutil.which("sccache"):
        return None

    env = os.environ.copy()
    env["SCCACHE_DIR"] = str(RDNA_SOURCE.sccache_dir)

    result = subprocess.run(["sccache", "--show-stats", "--stats-format=json"], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        return None

    try:
        stats = json.loads(result.stdout)["stats"]
        hits = stats["cache_hits"]["counts"]
        misses = stats["cache_misses"]["counts"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None

    return {
        "hits": sum(v for v in hits.values() if isinstance(v, int)),
        "misses": sum(v for v in misses.values() if isinstance(v, int)),
        "noncacheable": int(stats.get("non_cacheable_compilations", 0)),
    }


def output_path(command: str) -> str | None:
    output = command_output(command)
    return output.replace("\\", "/") if output else None


def estimate_phase(commands: list[str], history: list[tuple[str, float]], jobs: int) -> tuple[float, int]:
    if not commands:
        return 0, 0

    by_output: dict[str, list[float]] = defaultdict(list)

    for output, seconds in history:
        by_output[output].append(seconds)

    fallback = median(seconds for _, seconds in history) if history else None
    durations: list[float] = []

    for command in commands:
        output = output_path(command)
        samples = by_output.get(output or "", [])

        if samples:
            durations.append(samples[-1])
        elif fallback is not None:
            durations.append(fallback)

    if not durations:
        return 0, len(commands)

    durations.sort(reverse=True)

    workers = max(1, min(jobs, len(durations)))
    lanes = [0.0] * workers

    for duration in durations:
        index = min(range(workers), key=lanes.__getitem__)
        lanes[index] += duration

    return max(lanes), len(commands)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rdna-dir", default=str(RDNA_SOURCE.src_dir))
    parser.add_argument("--jobs", "-j", type=int, default=BUILD_DEFAULTS.jobs)
    args = parser.parse_args()

    build_dir = Path(args.rdna_dir) / "build"

    if not (build_dir / "build.ninja").exists():
        raise SystemExit(f"Missing {build_dir / 'build.ninja'}")

    pending = ninja_commands(build_dir)
    pending_compile = [x for x in pending if command_kind(x) == "compile"]
    pending_link = [x for x in pending if command_kind(x) == "link"]
    pending_archive = [x for x in pending if "llvm-ar.exe" in x.lower() or "llvm-lib.exe" in x.lower()]
    pending_other = [x for x in pending if x not in pending_compile + pending_link + pending_archive]

    history = read_ninja_log(build_dir)
    cache = sccache_stats()

    print("=== BUILD ESTIMATE ===")
    print(f"Pending compile : {len(pending_compile)}")
    print(f"Pending archive : {len(pending_archive)}")
    print(f"Pending link    : {len(pending_link)}")
    print(f"Pending other   : {len(pending_other)}")
    print(f"Parallel jobs   : {args.jobs}")

    if not pending_compile and not pending_archive and not pending_link:
        print("Build status    : up to date")
        return

    if history["compile"]:
        print(
            f"Compile history: {len(history['compile'])} commands, "
            f"median {median(x[1] for x in history['compile']):.2f}s"
        )

    if history["link"]:
        print(f"Link history   : {len(history['link'])} commands, median {median(x[1] for x in history['link']):.2f}s")

    if cache:
        total = cache["hits"] + cache["misses"] + cache["noncacheable"]
        if total:
            print(f"sccache        : {cache['misses']} misses / {cache['hits']} hits (historical)")
        else:
            print("sccache        : no recorded compilations")

    compile_time, _ = estimate_phase(pending_compile, history["compile"], args.jobs)
    link_time, _ = estimate_phase(pending_link, history["link"], 1)
    archive_time, _ = estimate_phase(pending_archive, history["link"], 1)

    estimate = compile_time + link_time + archive_time

    if estimate > 0:
        print(f"Estimated time : ~{estimate / 60:.1f} min")
    else:
        print("Estimated time : unavailable (no matching history)")


if __name__ == "__main__":
    main()
