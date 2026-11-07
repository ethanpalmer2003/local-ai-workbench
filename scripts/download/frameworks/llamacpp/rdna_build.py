"""Build ggml-org/llama.cpp layered with the stew675 RDNA-boosts patch stack.

Can be run standalone:
    python -m scripts.download.frameworks.llamacpp.rdna_build

or imported by another CLI.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.file_util import archive_path


@dataclass(frozen=True)
class RdnaSourceConfig:
    upstream_repo_url: str = "https://github.com/ggml-org/llama.cpp.git"
    boosts_repo_url: str = "https://github.com/stew675/llama-cpp-rdna-boosts.git"
    branch_name: str = "rdna-boosts"

    frameworks_dir: Path = Path(project_cfg.FRAMEWORKS_DIR)
    additions_dir: Path = frameworks_dir / "llamacpp" / "additions"
    src_dir: Path = frameworks_dir / "llamacpp" / "rdna"
    boosts_dir: Path = additions_dir / "llama-cpp-rdna-boosts"
    sccache_dir: Path = additions_dir / "sccache" / "cache"


@dataclass(frozen=True)
class BuildDefaults:
    gpu_target: str = "gfx1101"
    rocm_path: str = str(project_cfg.DATA_DIR / "ROCm" / "therock-dist-windows-gfx110X-all-10.2.0a20260927")
    rc_compiler: str = r"C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/rc.exe"
    jobs: int = 12
    skip_patch_setup: bool = False


RDNA_SOURCE = RdnaSourceConfig()
BUILD_DEFAULTS = BuildDefaults()


class UpdateError(Exception):
    pass


@dataclass
class ExtraPR:
    """A GitHub PR to layer on top, e.g. jadidbourbaki/llama.cpp#7."""

    repo: str  # "owner/repo"
    number: int

    @classmethod
    def parse(cls, spec: str) -> "ExtraPR":
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", spec)
        if m:
            return cls(repo=m.group(1), number=int(m.group(2)))
        m = re.match(r"([^/]+/[^#]+)#(\d+)", spec)
        if m:
            return cls(repo=m.group(1), number=int(m.group(2)))
        raise UpdateError(f"Can't parse PR spec: {spec!r} (want 'owner/repo#123' or a PR URL)")


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("> git " + " ".join(args))
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if check and result.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result


def cherry_pick_in_progress(src_dir: Path) -> bool:
    return (src_dir / ".git" / "CHERRY_PICK_HEAD").exists()


def am_in_progress(src_dir: Path) -> bool:
    return (src_dir / ".git" / "rebase-apply").exists()


def discover_rdna_patches(boosts_dir: Path) -> list[Path]:
    patches_dir = boosts_dir / "patches"
    if not patches_dir.exists():
        return []
    return sorted(patches_dir.glob("*.patch"))


def get_baseline_commit(boosts_dir: Path) -> str:
    return json.loads((boosts_dir / "release.json").read_text(encoding="utf-8"))["base"]


def apply_patch_one(src_dir: Path, patch_file: Path) -> tuple[bool, str]:
    result = subprocess.run(["git", "am", str(patch_file)], cwd=src_dir, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    subprocess.run(["git", "am", "--abort"], cwd=src_dir, capture_output=True, text=True)
    reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git am failed"
    return False, reason


def cherry_pick_one(src_dir: Path, ref: str) -> tuple[bool, str]:
    result = subprocess.run(["git", "cherry-pick", ref], cwd=src_dir, capture_output=True, text=True)
    if result.returncode == 0:
        return True, ""
    subprocess.run(["git", "cherry-pick", "--abort"], cwd=src_dir, capture_output=True, text=True)
    reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "cherry-pick failed"
    return False, reason


def apply_patch_files(src_dir: Path, patches: list[Path], label: str, skipped: list[tuple[str, str]]) -> int:
    applied = 0
    for patch in patches:
        ok, reason = apply_patch_one(src_dir, patch)
        if ok:
            applied += 1
        else:
            print(f"  SKIPPED {patch.name} ({label}): {reason}")
            skipped.append((patch.name, reason))
    return applied


def cherry_pick_refs(src_dir: Path, refs: list[str], label: str, skipped: list[tuple[str, str]]) -> int:
    applied = 0
    for ref in refs:
        ok, reason = cherry_pick_one(src_dir, ref)
        if ok:
            applied += 1
        else:
            print(f"  SKIPPED {ref} ({label}): {reason}")
            skipped.append((ref, reason))
    return applied


def setup_rdna_source(
    src_dir: Path, explicit_patches: list[str] | None, extra_prs: list[ExtraPR], source: RdnaSourceConfig = RDNA_SOURCE
) -> list[tuple[str, str]]:

    boosts_dir = source.boosts_dir

    if not boosts_dir.exists():
        print(f"Cloning patches repo {source.boosts_repo_url} -> {boosts_dir}")
        boosts_dir.parent.mkdir(parents=True, exist_ok=True)
        run_git(["clone", source.boosts_repo_url, str(boosts_dir)], cwd=boosts_dir.parent)
    else:
        print(f"Updating patches repo: {boosts_dir}")
        run_git(["fetch", "origin"], cwd=boosts_dir)
        run_git(["reset", "--hard", "origin/main"], cwd=boosts_dir)

    baseline_commit = get_baseline_commit(boosts_dir)

    if not src_dir.exists():
        print(f"Cloning {source.upstream_repo_url} -> {src_dir}")
        run_git(["clone", source.upstream_repo_url, str(src_dir)], cwd=src_dir.parent)
    else:
        print(f"Reusing existing checkout: {src_dir}")
        run_git(["fetch", "origin"], cwd=src_dir)

    if cherry_pick_in_progress(src_dir) or am_in_progress(src_dir):
        raise UpdateError(f"A cherry-pick or git am is still in progress in {src_dir}. Resolve or abort it first.")

    print(f"Checking out baseline {baseline_commit}")
    run_git(["checkout", baseline_commit], cwd=src_dir)
    run_git(["checkout", "-B", source.branch_name], cwd=src_dir)

    all_patches = discover_rdna_patches(boosts_dir)
    patches_to_apply = []

    if explicit_patches:
        for ep in explicit_patches:
            matches = [p for p in all_patches if ep in p.name]
            if matches:
                patches_to_apply.extend(matches)
            else:
                print(f"Warning: No patch found matching '{ep}'")
        patches_to_apply = sorted(set(patches_to_apply))
        print(f"Applying {len(patches_to_apply)} explicitly-requested patch(es)")
    else:
        patches_to_apply = all_patches
        print(f"Discovered {len(patches_to_apply)} rdna-boosts patch(es)")

    skipped: list[tuple[str, str]] = []
    applied = apply_patch_files(src_dir, patches_to_apply, label="rdna-boosts", skipped=skipped)
    print(f"Applied {applied}/{len(patches_to_apply)} rdna-boosts patch(es)")

    for pr in extra_prs:
        print(f"Layering extra PR {pr.repo}#{pr.number}")
        pr_repo_url = f"https://github.com/{pr.repo}.git"
        local_branch = f"pr-{pr.repo.replace('/', '-')}-{pr.number}"
        run_git(["fetch", pr_repo_url, f"pull/{pr.number}/head:{local_branch}"], cwd=src_dir)
        merge_base = run_git(["merge-base", "HEAD", local_branch], cwd=src_dir).stdout.strip()
        commits = run_git(["rev-list", "--reverse", f"{merge_base}..{local_branch}"], cwd=src_dir).stdout.split()
        if not commits:
            print(f"  no new commits in {pr.repo}#{pr.number}, skipping")
            continue
        pr_applied = cherry_pick_refs(src_dir, commits, label=f"{pr.repo}#{pr.number}", skipped=skipped)
        print(f"  applied {pr_applied}/{len(commits)} commit(s) from {pr.repo}#{pr.number}")

    return skipped


def build_rdna(
    src_dir: Path,
    rocm_path: Path,
    gpu_target: str,
    extra_cmake_args: list[str],
    jobs: int | None,
    defaults: BuildDefaults = BUILD_DEFAULTS,
    source: RdnaSourceConfig = RDNA_SOURCE,
) -> None:
    build_dir = src_dir / "build"
    if not (build_dir / "build.ninja").exists():
        print(f"Archiving old build dir: {build_dir}")
        archive_path(build_dir, src_dir)
    else:
        print(f"Reusing existing build directory: {build_dir}")

    llvm_path = rocm_path / "lib" / "llvm"
    env = os.environ.copy()

    env["HIP_PATH"] = str(rocm_path)
    env["LLVM_PATH"] = str(llvm_path)
    env["HIP_PLATFORM"] = "amd"
    env["PATH"] = f"{rocm_path}\\bin;{llvm_path}\\bin;" + env.get("PATH", "")
    env["SCCACHE_DIR"] = str(source.sccache_dir)

    configure_cmd = [
        "cmake",
        "-S",
        ".",
        "-B",
        "build",
        "-G",
        "Ninja",
        f"-DGPU_TARGETS={gpu_target}",
        "-DGGML_HIP=ON",
        f"-DCMAKE_C_COMPILER={llvm_path / 'bin' / 'amdclang.exe'}",
        f"-DCMAKE_CXX_COMPILER={llvm_path / 'bin' / 'amdclang++.exe'}",
        f"-DCMAKE_RC_COMPILER={defaults.rc_compiler}",
        "-DCMAKE_BUILD_TYPE=Release",
    ]

    # - GGML_HIP_ROCWMMA_FATTN is intentionally NOT passed: upstream removed the
    #   rocWMMA FA kernel (PR #26046) as obsolete - fattn-mma-f16.cuh supersedes
    #   it on all relevant AMD hardware, so the flag is a no-op
    configure_cmd.extend(extra_cmake_args)

    if shutil.which("sccache"):
        print("Found sccache in PATH; enabling compiler caching.")
        configure_cmd.extend(["-DCMAKE_C_COMPILER_LAUNCHER=sccache", "-DCMAKE_CXX_COMPILER_LAUNCHER=sccache"])

    print("Configuring:\n  " + " ".join(configure_cmd))
    subprocess.run(configure_cmd, cwd=src_dir, env=env, check=True)

    build_cmd = ["cmake", "--build", "build"] + (["-j", str(jobs)] if jobs else ["-j"])
    print("Building:\n  " + " ".join(build_cmd))
    subprocess.run(build_cmd, cwd=src_dir, env=env, check=True)

    print("\nBuild complete.")
    print(
        "Reminder: '--spec-type draft-mtp-adaptive' is a llama-cli/server runtime flag "
        "(from the adaptive-mtp patch), not a build option - pass it when you launch the exe."
    )


def add_arguments(parser: argparse.ArgumentParser | argparse._ArgumentGroup) -> None:
    parser.add_argument(
        "--build-llamacpp-rdna",
        action="store_true",
        help="build ggml-org/llama.cpp + stew675 RDNA patches instead of the normal update loop",
    )
    parser.add_argument(
        "--rdna-dir", default=str(RDNA_SOURCE.src_dir), help="checkout/build directory (default: %(default)s)"
    )
    parser.add_argument("--rocm-path", default=BUILD_DEFAULTS.rocm_path, help="ROCm install dir (default: %(default)s)")
    parser.add_argument(
        "--gpu-target",
        default=BUILD_DEFAULTS.gpu_target,
        help="GPU_TARGETS value for cmake (default: %(default)s, RDNA3/7800 XT)",
    )
    parser.add_argument(
        "--cmake-arg",
        action="append",
        default=[],
        metavar="-DFOO=BAR",
        help="extra cmake define, repeatable, e.g. --cmake-arg=-DGGML_NATIVE=OFF",
    )
    parser.add_argument(
        "--patches",
        action="append",
        default=[],
        metavar="0001,0003",
        help="exact patch file substrings to apply via git am instead of auto-discovering all .patch files (comma-separated, repeatable)",
    )
    parser.add_argument(
        "--extra-pr",
        action="append",
        default=[],
        metavar="owner/repo#123",
        help="extra GitHub PR to cherry-pick on top, repeatable (also accepts a PR URL)",
    )
    parser.add_argument(
        "--skip-patch-setup",
        action=argparse.BooleanOptionalAction,
        default=BUILD_DEFAULTS.skip_patch_setup,
        help="skip clone/patch step and just (re)build the existing checkout",
    )
    parser.add_argument(
        "--jobs", "-j", type=int, default=BUILD_DEFAULTS.jobs, help="parallel build jobs (default: %(default)s)"
    )


def run(args: argparse.Namespace) -> None:
    src_dir = Path(args.rdna_dir)
    boosts_dir = RDNA_SOURCE.boosts_dir
    state_file = src_dir / ".build_state.json"

    extra_prs = [ExtraPR.parse(spec) for spec in args.extra_pr]
    explicit_patches: list[str] = [p for spec in args.patches for p in spec.split(",") if p]

    current_state = {"patches": explicit_patches, "extra_pr": args.extra_pr, "boosts_commit": ""}
    do_setup = not args.skip_patch_setup

    # FAIL-SAFE: Force setup if the directory doesn't exist yet
    if not src_dir.exists():
        if args.skip_patch_setup:
            print(f"Warning: Directory '{src_dir}' does not exist. Ignoring --skip-patch-setup and forcing git setup.")
        do_setup = True

    # Auto-skip check
    if do_setup and not extra_prs and boosts_dir.exists() and src_dir.exists():
        run_git(["fetch", "origin"], cwd=boosts_dir)
        current_state["boosts_commit"] = subprocess.run(
            ["git", "rev-parse", "origin/main"], cwd=boosts_dir, capture_output=True, text=True
        ).stdout.strip()
        if state_file.exists():
            try:
                if json.loads(state_file.read_text(encoding="utf-8")) == current_state:
                    print("No upstream updates or argument changes detected. Auto-skipping patch setup.")
                    do_setup = False
            except (OSError, json.JSONDecodeError):
                pass

    skipped: list[tuple[str, str]] = []
    if do_setup:
        skipped = setup_rdna_source(src_dir, explicit_patches or None, extra_prs)
        # Save state after successful setup
        if boosts_dir.exists():
            current_state["boosts_commit"] = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=boosts_dir, capture_output=True, text=True
            ).stdout.strip()
            state_file.write_text(json.dumps(current_state))
    else:
        print("Skipping git setup/patch step; building as-is.")

    build_rdna(
        src_dir=src_dir,
        rocm_path=Path(args.rocm_path),
        gpu_target=args.gpu_target,
        extra_cmake_args=args.cmake_arg,
        jobs=args.jobs,
    )

    if skipped:
        print(f"\n{len(skipped)} patch(es)/commit(s) skipped (didn't apply cleanly):")
        for ref, reason in skipped:
            print(f"  - {ref}: {reason}")
        print("Apply any of these manually if you need them.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args()
    try:
        run(args)
    except UpdateError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)
    print("\n=== COMPLETE ===")


if __name__ == "__main__":
    main()
