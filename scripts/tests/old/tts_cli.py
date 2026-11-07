"""Launch installed speech CLIs using their canonical component paths."""

import argparse
import os
import subprocess
import sys

from scripts.config import project_config as project_cfg
from scripts.launchers.runtime.execution_context import require_native_execution


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--framework", choices=("piper", "sherpa-onnx"), required=True)
    selection, arguments = parser.parse_known_args()
    require_native_execution(selection.framework)
    root = project_cfg.component("tts/" + selection.framework).framework_dir
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    if selection.framework == "piper":
        if not (root / "piper/__main__.py").is_file():
            parser.error("Piper is missing; run update_frameworks --only tts/piper")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(root), env.get("PYTHONPATH"))))
        command = [sys.executable, "-m", "piper", *arguments]
    else:
        exe = root / "bin/sherpa-onnx-offline-tts.exe"
        if not exe.is_file():
            parser.error("sherpa-onnx is missing; run update_frameworks --only tts/sherpa-onnx")
        env["PATH"] = os.pathsep.join((str(root / "bin"), str(root / "lib"), env.get("PATH", "")))
        command = [str(exe), *arguments]
    return subprocess.run(command, cwd=project_cfg.BASE_DIR, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
