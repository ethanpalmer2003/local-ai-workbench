import argparse
import base64
import os
import sys
from datetime import datetime
from pathlib import Path

from scripts.launchers import launcher_config as cfg
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.launch_util import (
    build_cli_args,
    launch_process,
    prepare_service_port,
    print_ready,
    wait_for_exit,
)
from scripts.launchers.launcher_config import ConsoleTerminalLaunchMode
from scripts.launchers.proxy_util import run_json_proxy


def build_dir(build: str | None = None) -> Path:
    return cfg.SDCPP_BUILDS[cfg.SDCPP_SERVICE.build if build is None else build]


def launch(
    port: int | None = None,
    extra_args: list[str] | None = None,
    mode: ConsoleTerminalLaunchMode | None = None,
    load_model_on_start: bool = True,
    log_file: str | None = None,
):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--build", choices=tuple(cfg.SDCPP_BUILDS), default=cfg.SDCPP_SERVICE.build)
    parser.add_argument("--model-profile", choices=tuple(cfg.SDCPP_MODELS), default=cfg.SDCPP_SERVICE.model)
    parser.add_argument("--usage-profile", choices=("standalone", "shared"), default="standalone")
    selection, native_args = parser.parse_known_args(extra_args or [])
    if selection.usage_profile == "shared":
        native_args = [*shared_gpu.IMAGE_ARGS, *native_args]
    cfg.SDCPP_SERVICE.model = selection.model_profile
    directory = build_dir(selection.build)
    server_exe = str(directory / "sd-server.exe")
    port = port if port is not None else cfg.SDCPP_SERVICE.port

    server_opts = {**cfg.SDCPP_SERVER_ARGS, "listen-ip": cfg.SDCPP_SERVICE.listen_ip, "listen-port": port}
    if load_model_on_start:
        server_opts["m"] = cfg.SDCPP_MODELS[selection.model_profile]
    else:
        server_opts.pop("m", None)
    args = build_cli_args(server_opts)

    cmd = [server_exe, *args, *native_args]

    proc = launch_process(
        cmd,
        title="SdCpp Server",
        cwd=str(directory),
        kill_ports=port,
        report_vram=True,
        mode=mode,
        log_file=log_file,
        env={"PATH": str(directory) + os.pathsep + os.environ.get("PATH", "")},
    )

    print_ready("sdcpp", port=port, args=cmd, model_profile=selection.model_profile)
    return proc


def _image_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "png"


def save_generated_images(response: dict[str, object], request: dict[str, object]) -> None:
    """Proxy on_response hook:
    - write returned images to cfg.SDCPP_OUT_DIR (optional setting, blank disables)
    - bytes are saved as-is, so the extension follows the format the server actually returned
    """
    if not cfg.SDCPP_SAVE_OUTPUTS or request.get("_skip_save"):
        return
    data = response.get("data")
    if not isinstance(data, list):
        return

    out_dir = Path(cfg.SDCPP_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    for i, item in enumerate(data):
        b64 = item.get("b64_json") if isinstance(item, dict) else None
        if not isinstance(b64, str):
            continue
        raw = base64.b64decode(b64)
        path = out_dir / f"sdcpp_{stamp}_{i}.{_image_ext(raw)}"
        path.write_bytes(raw)
        print(f"[sdcpp] saved {path.name}")


def run_saving_proxy(extra_args: list[str] | None = None) -> None:
    """Pass-through proxy for standalone mode when SDCPP_OUT_DIR is set:
    - the raw server moves to the internal port
    - the proxy re-serves the public port untouched, writing each generated image to SDCPP_OUT_DIR
    - the raw binary has no output option of its own to hook
    """
    port = cfg.SDCPP_SERVICE.port
    internal_port = cfg.SDCPP_SERVICE.internal_port
    prepare_service_port(port, "SdCpp Server")
    launch(port=internal_port, extra_args=extra_args, mode=ConsoleTerminalLaunchMode.MERGE)

    run_json_proxy(
        cfg.SDCPP_SERVICE, f"http://127.0.0.1:{internal_port}", tag="sdcpp", on_response=save_generated_images
    )


def main() -> None:
    if cfg.SDCPP_SAVE_OUTPUTS:
        run_saving_proxy(extra_args=sys.argv[1:])
        return

    proc = launch(extra_args=sys.argv[1:], mode=ConsoleTerminalLaunchMode.MERGE)
    wait_for_exit(proc)


if __name__ == "__main__":
    main()
