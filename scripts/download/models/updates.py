"""Report stale sources and newer releases for catalog models.

Read-only: compares each entry's pinned Hugging Face file with the repository, and looks for a higher
version token in the same family. A replacement stays an explicit `model_admin replace` step.
"""

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.config import project_config as project_cfg
from scripts.config.models import MODELS as MODELS
from scripts.config.models import ModelDownload as ModelDownload
from scripts.download.models.hub_sources import parse_url

RELEASE = re.compile(r"^(?P<stem>.+?)-v(?P<version>\d+(?:\.\d+)*)(?:-GGUF)?$")
LIMIT = 30


class Hub(Protocol):
    def model_info(self, repo_id: str, *, revision: str | None = None, files_metadata: bool = False) -> Any: ...

    def list_models(self, *, search: str, limit: int) -> Any: ...


@dataclass
class Row:
    label: str
    source: str
    installed: str
    upstream: str
    newer: str


def _size(value: int | None) -> str:
    return f"{value / 1024**3:.1f} GiB" if value else "-"


def _release(repo_id: str) -> tuple[str, tuple[int, ...]] | None:
    """A versioned release repository: `.../Family-v1.2-GGUF` -> ('Family', (1, 2))."""
    match = RELEASE.match(repo_id.rsplit("/", 1)[-1])
    if not match:
        return None
    return match.group("stem"), tuple(int(part) for part in match.group("version").split("."))


def _newer(api: Hub, repo_id: str) -> str:
    """The highest release version above the pinned one for the same family, if any."""
    release = _release(repo_id)
    if release is None:
        return ""
    stem, current = release
    try:
        repos = list(api.list_models(search=stem, limit=LIMIT))
    except Exception:  # - a search failure only loses the hint, never a finding
        return ""
    best: tuple[tuple[int, ...], str] | None = None
    for repo in repos:
        other = _release(repo.id)
        if other is None or other[0] != stem or other[1] <= current:
            continue
        if best is None or other[1] > best[0]:
            best = (other[1], ".".join(str(part) for part in other[1]))
    return best[1] if best else ""


def _installed(model: ModelDownload) -> int | None:
    try:
        return model.path.stat().st_size
    except OSError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pinned(api: Hub, model: ModelDownload) -> tuple[Any, Any] | None:
    if not model.url:
        return None
    source = parse_url(model.url)
    try:
        info = api.model_info(source.repo_id, revision=source.revision, files_metadata=True)
    except Exception:  # - an unreachable repository is reported, not raised
        return None
    sibling = next((item for item in info.siblings or [] if item.rfilename == source.filename), None)
    return sibling, source


def check(model: ModelDownload, api: Hub, verify: bool = False) -> Row:
    installed = _installed(model)
    label, size = model.label, _size(installed)
    pinned = _pinned(api, model)
    if not model.url:
        return Row(label, "no url", size, "-", "")
    if pinned is None:
        return Row(label, "unreachable", size, "-", "")
    sibling, source = pinned
    newer = _newer(api, source.repo_id)
    if sibling is None:
        return Row(label, "missing", size, "-", newer)
    upstream = _size(getattr(sibling, "size", None))
    installed_size = getattr(sibling, "size", None)
    if installed and installed_size and installed != installed_size:
        return Row(label, "changed", size, upstream, newer)
    lfs = getattr(sibling, "lfs", None)
    expected = getattr(lfs, "oid", None) if lfs is not None else None
    if verify and expected and installed and expected != _sha256(model.path):
        return Row(label, "changed", size, upstream, newer)
    return Row(label, "ok", size, upstream, newer)


def _print(rows: list[Row]) -> None:
    print(f"{'entry':<52} {'source':<12} {'installed':>10} {'upstream':>10}  newer")
    for row in rows:
        print(f"{row.label:<52} {row.source:<12} {row.installed:>10} {row.upstream:>10}  {row.newer or '-'}")
    missing = [row for row in rows if row.source in {"missing", "unreachable"}]
    changed = [row for row in rows if row.source == "changed"]
    hints = [row for row in rows if row.newer]
    print(
        f"\n{len(rows)} checked, {len(missing)} with a broken source, "
        f"{len(changed)} with size drift, {len(hints)} with a newer release"
    )


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="check only these catalog labels")
    parser.add_argument("--all", action="store_true", help="include inactive entries")
    parser.add_argument("--verify", action="store_true", help="hash installed files and compare with the Hub")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    from huggingface_hub import HfApi

    api = HfApi(token=project_cfg.HF_TOKEN)
    models = [model for model in MODELS if model.url and (args.all or model.in_use)]
    if args.only:
        models = [model for model in models if model.label in set(args.only)]
    rows = [check(model, api, args.verify) for model in models]
    _print(rows)
    return 1 if any(row.source in {"missing", "unreachable"} for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
