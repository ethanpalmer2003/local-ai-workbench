"""Install the verified native Windows HRX runtime from its retained checkpoint."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg

CHECKPOINT_POINTER = project_cfg.component("llamacpp").state_dir / "hrx/latest-verified.json"


def verify_hashes(source: Path, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        with (source / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise RuntimeError(f"HRX checkpoint hash mismatch: {source / name}")


def install_runtime(source: Path, hashes: dict[str, str], checkpoint: Path) -> None:
    from scripts.launchers import launch_util

    if launch_util.llama_server_running():
        raise RuntimeError("Stop the configured llama-server before installing the HRX checkpoint")
    verify_hashes(source, hashes)
    runtime = cfg.LLAMACPP_BUILDS["hrx"].bin_dir
    runtime.mkdir(parents=True, exist_ok=True)
    for name in hashes:
        shutil.copy2(source / name, runtime / name)
    verify_hashes(runtime, hashes)
    (runtime / "checkpoint.json").write_text(
        json.dumps({"checkpoint": str(checkpoint), "sha256": hashes}, indent=2) + "\n", encoding="utf-8"
    )
    CHECKPOINT_POINTER.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_POINTER.write_text(json.dumps({"checkpoint": str(checkpoint)}) + "\n", encoding="utf-8")
    print(f"[OK] Installed verified HRX runtime: {runtime}")


def install_checkpoint(checkpoint: Path) -> None:
    hashes = json.loads((checkpoint / "artifacts/binaries.json").read_text(encoding="utf-8"))
    install_runtime(checkpoint / "temp/bin", hashes, checkpoint)


def restore_backup(backup: Path) -> None:
    previous = json.loads((backup / "checkpoint.json").read_text(encoding="utf-8"))
    install_runtime(backup, previous["sha256"], Path(previous["checkpoint"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, help="Restore this checkpoint instead of the current verified one")
    args = parser.parse_args()
    if args.checkpoint:
        checkpoint = args.checkpoint.resolve()
    else:
        marker = (
            CHECKPOINT_POINTER
            if CHECKPOINT_POINTER.exists()
            else cfg.LLAMACPP_BUILDS["hrx"].bin_dir / "checkpoint.json"
        )
        checkpoint = Path(json.loads(marker.read_text(encoding="utf-8"))["checkpoint"])
    install_checkpoint(checkpoint)


if __name__ == "__main__":
    main()
