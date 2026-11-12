"""KoboldCpp chat, selected transcription engine, and configured audio/image proxies."""

import argparse
import json
import subprocess
import time
from pathlib import Path
from threading import Thread
from typing import Any, cast

from scripts.config import paths
from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector as transcription
from scripts.launchers.koboldcpp import external_llm, kokoro
from scripts.launchers.launch_util import backend_ready, backend_running, launch_module, launch_process, port_listening
from scripts.launchers.launcher_config import ConsoleTerminalLaunchMode
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.runtime.browser import open_browser

PROXY_SERVICES = [
    ("Audiocpp", "scripts.launchers.audiocpp.audiocpp_proxy", "AudioCpp Proxy", cfg.AUDIOCPP_SERVICE),
    ("Sdcpp", "scripts.launchers.sdcpp.proxy", "SdCpp Proxy", cfg.SDCPP_SERVICE),
]

LOG_DIR = project_cfg.component("koboldcpp").logs_dir


def model_overrides(usage_profile: str = "standalone") -> dict[str, Any]:
    if usage_profile not in ("standalone", "shared"):
        raise ValueError(f"Unknown usage profile: {usage_profile}")
    options = dict(cfg.KOBOLDCPP_MODEL_KCPPS_OVERRIDES.get(cfg.KOBOLDCPP_SERVICE.model, {}))
    if usage_profile == "shared":
        options.update(shared_gpu.KOBOLDCPP_MODEL_ARGS.get(cfg.KOBOLDCPP_SERVICE.model, {}))
    return options


def _service_config() -> dict[str, Any]:
    base = json.loads(cfg.KOBOLDCPP_SERVICE.config.read_text(encoding="utf-8"))
    if cfg.KOBOLDCPP_SERVICE.streaming_ui and base.get("launch"):
        raise ValueError("Set launch to false in the native Kobold config when using the streaming UI.")
    return base


def _server_options(usage_profile: str) -> dict[str, Any]:
    options = {**cfg.KOBOLDCPP_KCPPS_ARGS, **model_overrides(usage_profile), **kokoro.model_options()}
    if transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine):
        # - None skips the flag so the config file's empty whispermodel disables the built-in model; "" emits an empty CLI argument the console wrapper drops
        options["whispermodel"] = None
    if cfg.KOBOLDCPP_SERVICE.transcription_engine == cfg.AsrStartupEngine.GEMMA_KOBOLD:
        if cfg.kobold_chat_model_path() != cfg.GEMMA_AUDIO_ASR.model:
            raise ValueError("Gemma audio needs the matching Gemma 4 E4B chat model")
        options["mmproj"] = str(cfg.GEMMA_AUDIO_ASR.mmproj)
    if cfg.KOBOLDCPP_ADMIN_PASSWORD:
        options["adminpassword"] = cfg.KOBOLDCPP_ADMIN_PASSWORD
    return options


def _model_config(options: dict[str, Any], no_model: bool) -> Path:
    if no_model:
        # - the UI runs without weights; llama.cpp serves the model
        options.pop("model", None)
        return external_llm.no_model_config()
    options["model"] = str(cfg.kobold_chat_model_path())
    return cfg.KOBOLDCPP_SERVICE.config


def _override_arguments(options: dict[str, Any]) -> list[str]:
    command = []
    for name, value in options.items():
        if value is False:
            raise ValueError(f"Set {name}=false in the native Kobold config; no negative CLI override is available")
        if value is None or value == "":
            continue
        command.append("--" + name)
        if value is not True:
            command.extend(str(item) for item in (value if isinstance(value, (list, tuple)) else [value]))
    return command


def server_command(usage_profile: str = "standalone", no_model: bool = False) -> list[str]:
    _ = _service_config()
    options = _server_options(usage_profile)
    alias_port = options.pop("port_param", options.get("port"))
    if alias_port != options.get("port"):
        raise ValueError("Kobold port and port_param overrides must agree")
    config_path = _model_config(options, no_model)
    command = [str(cfg.KOBOLDCPP_SERVICE.exe), "--config", str(paths.materialize(config_path))]
    if no_model:
        command.append("--nomodel")
    command.extend(_override_arguments(options))
    return command


def new_log_path(usage_profile: str = "standalone") -> Path:
    extra_args = model_overrides(usage_profile)
    tag_bits = "_".join(f"{k}{v}" for k, v in extra_args.items() if k in ("moecpu", "gpulayers", "overridetensors"))
    name = f"koboldcpp_{time.strftime('%Y%m%d-%H%M%S')}" + (f"_{tag_bits}" if tag_bits else "") + ".log"
    return LOG_DIR / name


def start_kobold(
    usage_profile: str = "standalone", no_model: bool = False, owned: bool = False
) -> tuple[subprocess.Popen[Any], Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = new_log_path(usage_profile)
    command = server_command(usage_profile, no_model)
    config_path = cfg.KOBOLDCPP_SERVICE.config
    process = launch_process(
        command,
        title="KoboldCpp Server",
        cwd=str(project_cfg.SCRIPTS_DIR),
        kill_ports=None
        if transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine) or kokoro.selected()
        else cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["port"]),
        report_vram=True,
        log_file=str(log_path),
        bind_job=owned,
    )
    return process, config_path, log_path


def print_summary(log_path: Path, usage_profile: str = "standalone") -> None:
    extra_args = model_overrides(usage_profile)
    print(f"GPU profile: {usage_profile}")
    print(f"Model:     {cfg.KOBOLDCPP_SERVICE.model}")
    print(f"GGUF:      {cfg.kobold_chat_model_path().name}")
    print(f"Context:   {cfg.KOBOLDCPP_KCPPS_ARGS['contextsize']}")
    if transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine):
        print(
            f"STT:       {transcription.model(cfg.KOBOLDCPP_SERVICE.transcription_engine)} ({cfg.KOBOLDCPP_SERVICE.transcription_engine.value})"
        )
    else:
        print(f"Whisper:   {cfg.KOBOLDCPP_KCPPS_ARGS['whispermodel']} (built-in)")
    print(f"Speech:    {cfg.KOBOLDCPP_SERVICE.speech_engine.value}")
    if kokoro.selected():
        backend = "CPU"
        if cfg.KOBOLDCPP_SERVICE.transcription_engine == cfg.AsrStartupEngine.AUDIOCPP:
            backend = "shared Vulkan"
        elif cfg.KOBOLDCPP_SERVICE.transcription_engine in (
            cfg.AsrStartupEngine.PARAKEET_STREAM,
            cfg.AsrStartupEngine.NEMO,
            cfg.AsrStartupEngine.SPEECHCPP,
            cfg.AsrStartupEngine.WHISPER_VULKAN,
            cfg.AsrStartupEngine.PARAKEET_V3,
        ):
            backend = "Vulkan"
        print(f"Kokoro:    {backend}, {cfg.KOKORO_TTS.threads} threads, voice {cfg.KOKORO_TTS.voice}")
    print(f"Extra args: {extra_args or 'none'}")
    print(f"Log:       {log_path}")
    audio_enabled = not kokoro.internal() and (kokoro.selected() or cfg.AUDIOCPP_SERVICE.enabled)
    print(f"Audiocpp:  {'on' if audio_enabled else 'off'}")
    print(f"Sdcpp:     {'on' if cfg.SDCPP_SERVICE.enabled else 'off'}")


def open_streaming_ui() -> None:
    # - Keep the original browser-storage origin; wait for the proxied page,
    #   since the proxy health endpoint can answer before Kobold has loaded.
    url = f"http://localhost:{cfg.KOBOLDCPP_SERVICE.streaming_ui_port}{cfg.KOBOLDCPP_SERVICE.streaming_ui_path}"
    backend_url = f"http://127.0.0.1:{cfg.KOBOLDCPP_KCPPS_ARGS['port']}/"
    print(f"KoboldCpp Lite Proxy: {url}")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if not backend_ready(backend_url) or not backend_ready(url):
            time.sleep(1)
            continue
        open_browser(url)
        return
    print(f"KoboldCpp Lite Proxy page not ready after 120s; open {url} once startup finishes")


def start_proxy_services(processes: list[tuple[str, subprocess.Popen[Any]]], usage_profile: str) -> None:
    for name, script, title, service in PROXY_SERVICES:
        if name == "Audiocpp" and cfg.KOBOLDCPP_SERVICE.transcription_engine == cfg.AsrStartupEngine.AUDIOCPP:
            continue  # ASR and Kokoro share the already-started server.
        if name == "Audiocpp" and kokoro.selected():
            if not kokoro.internal():
                if backend_running(service.internal_port):
                    raise RuntimeError("AudioCpp port is occupied; close the existing audio session first")
                processes.append(
                    (
                        "Kokoro AudioCpp",
                        launch_process(
                            kokoro.audio_command(
                                service.internal_port,
                                backend="vulkan"
                                if cfg.KOBOLDCPP_SERVICE.transcription_engine
                                in (
                                    cfg.AsrStartupEngine.PARAKEET_STREAM,
                                    cfg.AsrStartupEngine.NEMO,
                                    cfg.AsrStartupEngine.SPEECHCPP,
                                    cfg.AsrStartupEngine.WHISPER_VULKAN,
                                    cfg.AsrStartupEngine.PARAKEET_V3,
                                )
                                else "cpu",
                            ),
                            title="Kokoro AudioCpp",
                            cwd=str(project_cfg.AUDIOCPP_BIN_DIR),
                            env=kokoro.audio_environment(),
                        ),
                    )
                )
            continue
        if service.enabled and service.mode == cfg.ServiceMode.PROXY:
            print(f"Starting {name} proxy...")
            # - DEPENDENT: kobold is a supervisor - its exit (any reason)
            #   tears the children down via the job object; no manual kill
            #   loop needed
            processes.append(
                (
                    name,
                    launch_module(
                        script,
                        title,
                        mode=ConsoleTerminalLaunchMode.SPLIT_DEPENDENT,
                        extra_args=["--usage-profile", usage_profile],
                    ),
                )
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=sorted(cfg.KOBOLDCPP_MODELS), help="Select a configured chat model")
    parser.add_argument("--speech-engine", choices=[engine.value for engine in cfg.KoboldcppSpeechStartupEngine])
    parser.add_argument("--practice-ui", action="store_true", help="Open the common language-practice interface")
    parser.add_argument("--transcription-engine", choices=[engine.value for engine in cfg.AsrStartupEngine])
    parser.add_argument(
        "--with-image",
        action="store_true",
        default=cfg.KOBOLD_CHAT.image == "with",
        help="Include sd.cpp using the shared GPU profile (default from the overlay's chat.image)",
    )
    parser.add_argument("--usage-profile", choices=("standalone", "shared"), default="shared")
    parser.add_argument(
        "--llm",
        choices=("kobold", "external"),
        default="kobold",
        help="external: KoboldCpp runs without weights and llama.cpp serves the model",
    )
    parser.add_argument(
        "--image-on-demand",
        action="store_true",
        default=cfg.KOBOLD_CHAT.image == "on-demand",
        help="Keep Kobold loaded; swap TTS/Nova through native APIs (default from the overlay's chat.image)",
    )
    parser.add_argument(
        "--no-image", action="store_true", help="Start without image generation whatever the overlay says"
    )
    return parser


def apply_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> bool:
    """Fold the flags into service settings and return whether the LLM runs externally."""
    if args.practice_ui:
        cfg.KOBOLDCPP_SERVICE.streaming_ui_path = "/practice"
        # - the practice page implies the practice model unless the caller names one
        if not args.model:
            cfg.KOBOLDCPP_SERVICE.model = cfg.LANGUAGE_PRACTICE.llm_model
    if args.model:
        cfg.KOBOLDCPP_SERVICE.model = args.model
    if args.speech_engine:
        cfg.KOBOLDCPP_SERVICE.speech_engine = cfg.KoboldcppSpeechStartupEngine(args.speech_engine)
    if args.transcription_engine:
        cfg.KOBOLDCPP_SERVICE.transcription_engine = cfg.AsrStartupEngine(args.transcription_engine)
    if transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine) and (
        not cfg.KOBOLDCPP_SERVICE.streaming_ui or args.image_on_demand
    ):
        parser.error("External transcription requires the Lite proxy and the normal language-practice lifecycle")
    if kokoro.selected() and args.image_on_demand:
        parser.error("Kokoro comparison profiles use their own speech lifecycle; omit --image-on-demand")
    external = args.llm == "external"
    if external and not cfg.KOBOLDCPP_SERVICE.streaming_ui:
        parser.error("External LLM needs the Lite proxy so the page can point at llama.cpp")
    if external and args.image_on_demand:
        parser.error("External LLM uses the normal lifecycle; omit --image-on-demand")
    return external


def check_profile_ports() -> None:
    """Refuse an occupied port instead of starting a second session on the same profile."""
    if not (kokoro.selected() or transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine)):
        return
    ports = [cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["port"])]
    if cfg.KOBOLDCPP_SERVICE.streaming_ui:
        ports.append(cfg.KOBOLDCPP_SERVICE.streaming_ui_port)
    if (
        kokoro.selected()
        and not kokoro.internal()
        and cfg.KOBOLDCPP_SERVICE.transcription_engine != cfg.AsrStartupEngine.AUDIOCPP
    ):
        ports.append(cfg.AUDIOCPP_SERVICE.internal_port)
    occupied = [port for port in ports if backend_running(port) or port_listening(port)]
    if occupied:
        raise RuntimeError(f"Kobold profile ports are occupied: {occupied}; close the existing session first")


def start_lite_proxy(external: bool) -> subprocess.Popen[Any]:
    proxy_args = [
        "--speech-engine",
        cfg.KOBOLDCPP_SERVICE.speech_engine.value,
        "--transcription-engine",
        cfg.KOBOLDCPP_SERVICE.transcription_engine.value,
    ]
    if external:
        proxy_args += ["--external-endpoint", external_llm.base_url(), "--external-model", external_llm.ALIAS]
    return launch_module(
        "scripts.launchers.koboldcpp.kobold_lite",
        "KoboldCpp Lite Proxy",
        mode=ConsoleTerminalLaunchMode.SPLIT_DEPENDENT,
        extra_args=proxy_args,
    )


def start_stack(external: bool, usage_profile: str) -> tuple[list[tuple[str, subprocess.Popen[Any]]], Path]:
    processes: list[tuple[str, subprocess.Popen[Any]]] = []
    if transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine):
        asr_process = transcription.backend(cfg.KOBOLDCPP_SERVICE.transcription_engine).start()
        if asr_process is not None:
            processes.append(("Transcription", asr_process))
    process, _, log_path = start_kobold(usage_profile, no_model=external)
    processes.append(("KoboldCpp Server", process))
    if external:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        processes.insert(
            0, ("llama.cpp", external_llm.start(LOG_DIR / f"llamacpp_external_{time.strftime('%Y%m%d-%H%M%S')}.log"))
        )
    if cfg.KOBOLDCPP_SERVICE.streaming_ui and not backend_running(cfg.KOBOLDCPP_SERVICE.streaming_ui_port):
        processes.append(("Streaming Lite", start_lite_proxy(external)))
    start_proxy_services(processes, usage_profile)
    return processes, log_path


def supervise(processes: list[tuple[str, subprocess.Popen[Any]]]) -> None:
    """Block while the stack runs; a stopped dependency ends the session."""
    while processes:
        time.sleep(2)
        for name, process in processes[:]:
            if process.poll() is None:
                continue
            processes.remove((name, process))
            if name == "KoboldCpp Server":
                return
            if name == "Transcription":
                raise RuntimeError("Transcription server stopped; close this session and relaunch language practice")
            if name == "llama.cpp":
                raise RuntimeError("llama.cpp server stopped; close this session and relaunch")


def fold_image_flags(args: argparse.Namespace) -> None:
    """--no-image clears whatever the overlay default or another flag selected."""
    if args.no_image:
        args.with_image = args.image_on_demand = False


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    fold_image_flags(args)
    external = apply_options(args, parser)
    if args.image_on_demand:
        from scripts.launchers.runtime.image_on_demand import run

        run(lambda: start_kobold("standalone")[0], open_streaming_ui if cfg.KOBOLDCPP_SERVICE.streaming_ui else None)
        return
    if args.with_image:
        cfg.SDCPP_SERVICE.enabled = True
    check_profile_ports()
    try:
        processes, log_path = start_stack(external, args.usage_profile)
        print_summary(log_path, args.usage_profile)
        if cfg.KOBOLDCPP_SERVICE.streaming_ui:
            Thread(target=open_streaming_ui, daemon=True).start()
        supervise(processes)
    except KeyboardInterrupt:
        print("\nStopping...")


if __name__ == "__main__":
    main()
