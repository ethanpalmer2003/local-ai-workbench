"""Labeled model sources and exact destinations; inactive candidates remain discoverable."""

import argparse
from pathlib import Path

from scripts.config.models import MODELS as MODELS
from scripts.config.models import ModelDownload as ModelDownload
from scripts.download.models.hub_sources import parse_url


def download_model(
    model: ModelDownload, mode: str = "stream", range_download: bool = False, resume_file: Path | None = None
) -> None:
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
    print(f"{model.label} -> {model.path}")
    if range_download:
        from scripts.download.models.hub_transfer import download_ranges

        download_ranges(parse_url(model.url), model.path, resume_file)
        return
    from scripts.download.models import transfer

    if mode == "stream":
        transfer.download_stream(model)
        return
    transfer.download_hub(model)


def _parser() -> argparse.ArgumentParser:
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
        "--mode",
        choices=("stream", "hub"),
        default="stream",
        help="stream: plain HTTP ranges with resume (default); hub: the Hub client, cache and Xet aware",
    )
    parser.add_argument(
        "--range-download",
        action="store_true",
        help="Use authenticated, verified HTTP ranges instead of Hub cache transfer",
    )
    parser.add_argument(
        "--resume-file", type=Path, help="Existing contiguous partial file; requires --range-download and one model"
    )
    return parser


def _matches(model: ModelDownload, args: argparse.Namespace) -> bool:
    return (
        (not args.model or model.label in args.model)
        and (not args.active or model.in_use)
        and (not args.inactive or not model.in_use)
        and (not args.group or model.group == args.group or model.group.startswith(args.group + "/"))
    )


def _print_models(models: list[ModelDownload]) -> None:
    for model in models:
        print(f"{'IN USE' if model.in_use else 'INACTIVE'}  {model.label}")
        print(f"  Download: {model.url or 'NOT CONFIGURED'}")
        if model.source_page:
            print(f"  Model page: {model.source_page}")
        print(f"  Target: {model.path}")
        if model.notes:
            print(f"  Note: {model.notes}")


def _start_downloads(models: list[ModelDownload], args: argparse.Namespace) -> None:
    for model in models:
        if args.range_download:
            download_model(model, args.mode, True, args.resume_file)
        else:
            download_model(model, args.mode)


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list and args.download:
        parser.error("--list and --download cannot be combined")
    if args.download and not (args.model or args.active):
        parser.error("Downloads require --model or --active; use --list to inspect first")
    models = [model for model in MODELS if _matches(model, args)]
    if not models:
        parser.error("No catalog entries match the selection")
    if not args.download:
        _print_models(models)
        return
    if args.resume_file and (not args.range_download or len(models) != 1):
        parser.error("--resume-file requires --range-download and exactly one model")
    missing = [model.label for model in models if model.url is None]
    if missing:
        parser.error(f"Missing source URLs: {', '.join(missing)}")
    _start_downloads(models, args)
