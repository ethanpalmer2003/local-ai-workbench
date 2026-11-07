"""Labeled model sources and exact destinations; inactive candidates remain discoverable."""

import argparse
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.config.models import MODELS as MODELS
from scripts.config.models import ModelDownload as ModelDownload
from scripts.download.models.hub_sources import parse_url


def download_model(model: ModelDownload, range_download: bool = False, resume_file: Path | None = None) -> None:
    if model.path.is_file() and model.path.stat().st_size > 0:
        print(f"[SKIP] Already present: {model.path}")
        return
    if model.url is None:
        raise ValueError(f"No download source recorded for {model.label}: {model.notes}")
    if not model.url.startswith("https://huggingface.co/"):
        from scripts.download.models.http_transfer import download_verified

        if range_download or resume_file:
            raise ValueError("Range/resume mode is only configured for Hugging Face files")
        download_verified(model.url, model.path, model.sha256)
        return
    from huggingface_hub import hf_hub_download

    source = parse_url(model.url)
    print(f"{model.label} -> {model.path}")
    if range_download:
        from scripts.download.models.hub_transfer import download_ranges

        download_ranges(source, model.path, resume_file)
        return
    model.path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=source.repo_id,
            filename=source.filename,
            revision=source.revision,
            token=project_cfg.HF_TOKEN,
            local_dir=str(model.path.parent),
        )
    )
    if downloaded != model.path:
        downloaded.replace(model.path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="List model sources or explicitly download selected catalog entries.")
    parser.add_argument("--list", action="store_true", help="List only (also the default)")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--model", nargs="+", choices=[model.label for model in MODELS])
    selection.add_argument("--active", action="store_true", help="Select entries marked in_use")
    selection.add_argument("--inactive", action="store_true", help="List old, optional, or unresolved entries")
    groups = {part for model in MODELS for part in (model.group, model.group.split("/")[0])}
    parser.add_argument("--group", choices=sorted(groups))
    parser.add_argument("--download", action="store_true", help="Download selected entries; otherwise only list")
    parser.add_argument(
        "--range-download",
        action="store_true",
        help="Use authenticated, verified HTTP ranges instead of Hub cache transfer",
    )
    parser.add_argument(
        "--resume-file", type=Path, help="Existing contiguous partial file; requires --range-download and one model"
    )
    args = parser.parse_args(argv)
    if args.list and args.download:
        parser.error("--list and --download cannot be combined")
    if args.download and not (args.model or args.active):
        parser.error("Downloads require --model or --active; use --list to inspect first")
    models = [
        model
        for model in MODELS
        if (not args.model or model.label in args.model)
        and (not args.active or model.in_use)
        and (not args.inactive or not model.in_use)
        and (not args.group or model.group == args.group or model.group.startswith(args.group + "/"))
    ]
    if not models:
        parser.error("No catalog entries match the selection")
    if args.download:
        if args.resume_file and (not args.range_download or len(models) != 1):
            parser.error("--resume-file requires --range-download and exactly one model")
        missing = [model.label for model in models if model.url is None]
        if missing:
            parser.error(f"Missing source URLs: {', '.join(missing)}")
        for model in models:
            if args.range_download:
                download_model(model, True, args.resume_file)
            else:
                download_model(model)
        return
    for model in models:
        print(f"{'IN USE' if model.in_use else 'INACTIVE'}  {model.label}")
        print(f"  Download: {model.url or 'NOT CONFIGURED'}")
        if model.source_page:
            print(f"  Model page: {model.source_page}")
        print(f"  Target: {model.path}")
        if model.notes:
            print(f"  Note: {model.notes}")


if __name__ == "__main__":
    main()
