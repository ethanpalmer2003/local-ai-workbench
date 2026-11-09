"""Download catalog models; with no arguments, fetch only the active files that are missing.

This never looks for newer versions. `update_models` is the one that replaces an older release.
"""

import sys

from scripts.download.models import cli_download, download_catalog

ARBITRARY = {"--repo", "--url", "--file", "--local-dir", "--revision"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and ARBITRARY & set(args):
        cli_download.main(args)
        return 0
    download_catalog.main(args or ["--active", "--download"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
