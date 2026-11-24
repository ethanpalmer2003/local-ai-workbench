#!/usr/bin/env python3
"""Download a Hugging Face snapshot, file, or URL target."""

import argparse
import sys
from pathlib import Path

import huggingface_hub

from scripts.config import project_config as project_cfg
from scripts.download.models import DOWNLOAD_SECONDS
from scripts.download.models import download_catalog as download
from scripts.download.models.hub_sources import HubFile as HubFile
from scripts.download.models.hub_sources import parse_url as parse_url
from scripts.shared import consent


def download_snapshot(
    repo_id: str, token: str | None = None, revision: str = "main", local_dir: Path | None = None
) -> None:
    """Download a full model snapshot to the HF cache directory.

    - Uses snapshot_download into HF_MODELS_DIR
    """

    target = local_dir if local_dir is not None else project_cfg.HF_MODELS_DIR
    target.mkdir(parents=True, exist_ok=True)

    print(f"Repo     : {repo_id}")
    print(f"Revision : {revision}")
    print(f"Target   : {target}")
    print()

    huggingface_hub.snapshot_download(repo_id=repo_id, local_dir=str(target), revision=revision, token=token)

    print("\nDownload complete!")


def download_file(
    repo_id: str, filename: str, token: str | None = None, revision: str = "main", local_dir: Path | None = None
) -> None:
    """Download a single file from a HuggingFace repo.

    - Uses hf_hub_download into HF_MODELS_DIR
    """

    target = local_dir if local_dir is not None else project_cfg.HF_MODELS_DIR
    target.mkdir(parents=True, exist_ok=True)

    print(f"Repo     : {repo_id}")
    print(f"File     : {filename}")
    print(f"Target   : {target}")
    print()

    path = huggingface_hub.hf_hub_download(
        repo_id=repo_id, filename=filename, repo_type="model", local_dir=str(target), token=token, revision=revision
    )

    print(f"Downloaded to: {path}")
    print("Done!")


def main(argv: list[str] | None = None):
    given, arguments = consent.take(sys.argv[1:] if argv is None else argv)
    if any(arg in arguments for arg in ("--list", "--model", "--active", "--inactive", "--group", "--download")):
        download.main(consent.forward(given, arguments))
        return
    parser = argparse.ArgumentParser(description="Download models/files from HuggingFace.")
    parser.add_argument("--repo", help="HuggingFace repo ID (e.g., Qwen/Qwen3-AUDIOCPP-12Hz-1.7B-CustomVoice)")
    parser.add_argument("--file", help="Single file to download (requires --repo)")
    parser.add_argument("--url", help="Full HuggingFace URL (auto-extracts repo and filename)")
    parser.add_argument("--revision", help="Revision/branch (default: URL revision or main)")
    parser.add_argument("--local-dir", type=Path, help="Destination folder (default: huggingface/models)")

    args = parser.parse_args(arguments)

    if not args.repo and not args.url:
        parser.print_help()
        sys.exit(1)
    if not consent.ask("Model download", DOWNLOAD_SECONDS, given):
        raise SystemExit(1)

    repo_id = args.repo
    filename = args.file

    if args.url:
        target = parse_url(args.url)
        download_file(
            target.repo_id,
            target.filename,
            token=project_cfg.HF_TOKEN,
            revision=args.revision or target.revision,
            local_dir=args.local_dir,
        )
        return

    if args.file:
        if not repo_id:
            parser.print_help()
            sys.exit(1)
        download_file(
            repo_id, filename, token=project_cfg.HF_TOKEN, revision=args.revision or "main", local_dir=args.local_dir
        )
        return

    # - Default: download full snapshot
    if not repo_id:
        parser.print_help()
        sys.exit(1)

    download_snapshot(repo_id, token=project_cfg.HF_TOKEN, revision=args.revision or "main", local_dir=args.local_dir)


if __name__ == "__main__":
    main()
