import argparse
import json
import sys
import time
from pathlib import Path
from threading import Thread

from scripts.launchers import launcher_config as cfg
from scripts.launchers.launch_util import backend_ready, prepare_service_port, print_settings, trigger_preload
from scripts.launchers.proxy_restart import OwnedBackendLifecycle, ProxyRestartController, reload_proxy_configuration
from scripts.launchers.proxy_util import run_json_proxy
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.runtime.browser import open_browser
from scripts.launchers.sdcpp import server as sdcpp

TRANSFORM_PATHS = frozenset({"/v1/images/generations"})


def _transform(payload: dict[str, object]) -> dict[str, object]:
    payload.pop("_skip_save", None)  # internal marker, never forwarded upstream

    model = payload.get("model")
    if not model or str(model) not in cfg.SDCPP_PROXY_ACCEPTED_MODELS:
        payload["model"] = str(cfg.SDCPP_SERVICE.model)

    prompt = payload.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    payload["prompt"] = cfg.SDCPP_PROXY_PROMPT.build(prompt)
    print(f"[sdcpp-proxy] wrapped prompt: {payload['prompt'][:100]}...")

    # - fill in any generation params the request left out (or left null)
    for key, value in cfg.SDCPP_REQUEST_DEFAULTS.items():
        if key not in payload or payload[key] is None:
            payload[key] = value

    # OpenAI image requests only accept size; sampling controls use the native extension.
    if not payload.get("size"):
        payload["size"] = f"{payload['width']}x{payload['height']}"
    if "<sd_cpp_extra_args>" not in str(payload["prompt"]):
        native = {key: payload[key] for key in ("negative_prompt", "clip_skip", "seed")}
        native["sample_params"] = {
            "sample_method": payload["sampler_name"],
            "sample_steps": payload["steps"],
            "guidance": {"txt_cfg": payload["cfg_scale"]},
        }
        payload["prompt"] = f"{payload['prompt']} <sd_cpp_extra_args>{json.dumps(native)}</sd_cpp_extra_args>"

    return payload


def _trigger_sdcpp_preload() -> None:
    trigger_preload(
        enabled=cfg.SDCPP_SERVICE.warmup,
        tag="sdcpp",
        ready_url=ready_url("sdcpp", cfg.SDCPP_SERVICE.internal_port),
        url=f"http://127.0.0.1:{cfg.SDCPP_SERVICE.port}/v1/images/generations",
        payload={
            "prompt": " ",
            "width": 256,
            "height": 256,
            "steps": 1,
            "response_format": "b64_json",
            "_skip_save": True,  # warmup image, don't write it to SDCPP_OUT_DIR
        },
    )


def _open_test_page() -> None:
    url = f"http://127.0.0.1:{cfg.SDCPP_SERVICE.port}/"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if backend_ready(url):
            open_browser(url)
            return
        time.sleep(1)
    print(f"[sdcpp-proxy] test page not ready after 120s; open {url} once startup finishes")


def launch_proxy(extra_args: list[str] | None = None, open_test: bool = False) -> None:
    port = cfg.SDCPP_SERVICE.port
    internal_port = cfg.SDCPP_SERVICE.internal_port
    prepare_service_port(port, "SdCpp Proxy")
    print_settings("sdcpp-proxy", "request defaults", cfg.SDCPP_REQUEST_DEFAULTS)
    print_settings("sdcpp-proxy", "prompt", cfg.SDCPP_PROXY_PROMPT)
    forwarded = list(sys.argv[1:] if extra_args is None else extra_args)
    process = sdcpp.launch(port=internal_port, extra_args=forwarded, mode=cfg.ConsoleTerminalLaunchMode.MERGE)

    _trigger_sdcpp_preload()

    upstream = f"http://127.0.0.1:{internal_port}"
    service = cfg.SDCPP_SERVICE
    lifecycle = OwnedBackendLifecycle(
        process,
        lambda: sdcpp.launch(port=internal_port, extra_args=forwarded, mode=cfg.ConsoleTerminalLaunchMode.MERGE),
        ready_url("sdcpp", internal_port),
        lambda: None,
    )
    controller = ProxyRestartController(
        {"backend": lifecycle.restart, "proxy": lambda: reload_proxy_configuration(service, "SDCPP_SERVICE")},
        {"backend": [Path(cfg.__file__)], "proxy": [Path(cfg.__file__)]},
    )
    if open_test:
        Thread(target=_open_test_page, daemon=True).start()
    run_json_proxy(
        service,
        upstream,
        transform=_transform,
        on_response=sdcpp.save_generated_images,
        tag="sdcpp-proxy",
        restart_controller=controller,
        transform_paths=TRANSFORM_PATHS,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-test", action="store_true", help="Open the sd.cpp image test page when ready")
    args, forwarded = parser.parse_known_args()
    launch_proxy(extra_args=forwarded, open_test=args.open_test)


if __name__ == "__main__":
    main()
