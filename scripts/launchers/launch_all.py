"""
- Launch and monitor the configured service stack
"""

import time
from collections.abc import Callable
from subprocess import Popen
from typing import Any

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp
from scripts.launchers.launch_util import launch_module
from scripts.launchers.llamacpp import llamacpp, llamacpp_proxy


def stack_services() -> list[tuple[str, Callable[[], Any]]]:
    """
    - Launch order for the current config
    - Services with enabled=False are skipped entirely
    - In PROXY mode the proxy module owns the raw server (it spawns it
      internally); SERVER mode launches the raw binary directly
    """
    services: list[tuple[str, Callable[[], Any]]] = []

    if cfg.LLAMACPP_SERVICE.mode == cfg.ServiceMode.PROXY:
        services.append(("LlamaCpp Proxy", lambda: launch_module(llamacpp_proxy.MODULE, llamacpp_proxy.TITLE)))
    else:
        services.append(("llama.cpp", llamacpp.launch))

    if cfg.AUDIOCPP_SERVICE.enabled:
        if cfg.AUDIOCPP_SERVICE.mode == cfg.ServiceMode.SERVER:
            services.append(("audio.cpp", audiocpp.launch))
        elif cfg.AUDIOCPP_SERVICE.mode == cfg.ServiceMode.PROXY:
            services.append(
                ("AudioCpp Proxy", lambda: launch_module("scripts.launchers.audiocpp.audiocpp_proxy", "AudioCpp Proxy"))
            )

    if cfg.SDCPP_SERVICE.enabled:
        if cfg.SDCPP_SERVICE.mode == cfg.ServiceMode.SERVER:
            # - sdcpp.main() owns the SDCPP_OUT_DIR decision (raw server vs
            #   saving proxy)
            # - Spawning the module keeps that decision in one place
            services.append(("SdCpp Server", lambda: launch_module("scripts.launchers.sdcpp.server", "SdCpp Server")))
        elif cfg.SDCPP_SERVICE.mode == cfg.ServiceMode.PROXY:
            services.append(("SdCpp Proxy", lambda: launch_module("scripts.launchers.sdcpp.proxy", "SdCpp Proxy")))

    return services


def main() -> None:
    processes: list[tuple[str, Popen[Any]]] = []

    try:
        for name, launch in stack_services():
            print(f"Starting {name}...")
            process = launch()
            if not isinstance(process, Popen):
                raise TypeError(f"{name} launcher did not return a subprocess")
            processes.append((name, process))

        print("All processes started in separate windows.")
        while processes:
            time.sleep(2)
            processes = [(name, p) for name, p in processes if p.poll() is None]
    except KeyboardInterrupt:
        print("\nStopped watching. Child processes will be terminated.")


if __name__ == "__main__":
    main()
