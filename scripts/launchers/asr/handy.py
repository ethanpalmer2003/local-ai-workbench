"""Launch the portable Handy desktop app."""

import argparse
import subprocess

from scripts.config import project_config as project_cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help=argparse.SUPPRESS)
    args, native_args = parser.parse_known_args()
    if args.install:
        parser.error("Installation moved to `update_frameworks --only asr/handy`")
    executable = project_cfg.HANDY_APP_DIR / "handy.exe"
    if not executable.is_file():
        raise FileNotFoundError("Run bat/update_frameworks.bat --only asr/handy first")
    subprocess.Popen([str(executable), *native_args], cwd=project_cfg.HANDY_APP_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
