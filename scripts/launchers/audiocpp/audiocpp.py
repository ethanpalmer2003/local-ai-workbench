import argparse
import sys
from pathlib import Path

from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import build_cli_args, launch_process, print_ready, wait_for_exit
from scripts.launchers.launcher_config import ConsoleTerminalLaunchMode
from scripts.launchers.runtime import shared_gpu


def launch(
    port: int | None = None,
    extra_args: list[str] | None = None,
    report_vram: bool = True,
    mode: ConsoleTerminalLaunchMode | None = None,
    log_file: str | None = None,
):
    port = port if port is not None else cfg.AUDIOCPP_SERVICE.port
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--usage-profile", choices=("standalone", "shared"), default="standalone")
    selection, native_args = parser.parse_known_args(extra_args or [])
    server_args = {
        **cfg.AUDIOCPP_SERVER_ARGS,
        "config": str(paths.materialize(Path(cfg.AUDIOCPP_SERVER_ARGS["config"]))),
        "port": port,
        "model": str(cfg.AUDIOCPP_SERVICE.model),
    }
    if selection.usage_profile == "shared":
        server_args["config"] = str(shared_gpu.audio_config(Path(cfg.AUDIOCPP_SERVER_ARGS["config"]), port))
    cmd = [str(project_cfg.AUDIOCPP_SERVER_EXE), *build_cli_args(server_args), *native_args]

    proc = launch_process(
        cmd,
        title="AudioCpp Server",
        cwd=str(project_cfg.AUDIOCPP_BIN_DIR),
        kill_ports=port,
        report_vram=report_vram,
        mode=mode,
        log_file=log_file,
    )
    print_ready("audiocpp", port=port, args=cmd, config=server_args["config"])
    return proc


def main():
    proc = launch(extra_args=sys.argv[1:], mode=ConsoleTerminalLaunchMode.MERGE)
    wait_for_exit(proc)


if __name__ == "__main__":
    main()
