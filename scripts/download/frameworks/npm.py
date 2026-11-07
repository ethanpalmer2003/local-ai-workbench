"""Invoke npm through Node instead of the Windows command wrapper."""

import shutil
from pathlib import Path


def command() -> list[str]:
    npm = shutil.which("npm.cmd")
    if npm is None:
        raise FileNotFoundError("npm.cmd not found")
    return ["node", str(Path(npm).parent / "node_modules/npm/bin/npm-cli.js")]
