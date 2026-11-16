"""Download catalog models; with no arguments, fetch only the active files that are missing.

This never looks for newer versions. `update_models` is the one that replaces an older release.
"""

import sys

from scripts.download.models import cli_download, download_catalog
from scripts.shared import consent

ARBITRARY = {"--repo", "--url", "--file", "--local-dir", "--revision"}

# - sizes are unknown before the request, and a catalog or single repo is minutes of transfer
DOWNLOAD_SECONDS = 600


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    given = "--yes" in args
    args = [argument for argument in args if argument != "--yes"]
    if not consent.ask("Model download", DOWNLOAD_SECONDS, given):
        return 1
    if args and ARBITRARY & set(args):
        cli_download.main(args)
        return 0
    download_catalog.main(args or ["--active", "--download"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
