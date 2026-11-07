import importlib
import sys
from collections.abc import Callable
from pathlib import Path

from scripts.config.audiocpp import server as audio_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp, audiocpp_catalog, tts_text_processing
from scripts.launchers.audiocpp.tts_proxy import is_streaming_request, run_tts_json_proxy
from scripts.launchers.launch_util import prepare_service_port, print_settings, trigger_preload
from scripts.launchers.proxy_restart import OwnedBackendLifecycle, ProxyRestartController, reload_proxy_configuration
from scripts.launchers.runtime.backend_readiness import ready_url
from scripts.launchers.runtime.gpu_memory import get_gpu_memory_snapshot, report_vram_usage_async

Payload = dict[str, object]


def _transform(payload: Payload) -> Payload | None:
    if payload.pop("_comparison", False):
        audiocpp_catalog.validate_comparison(payload)
    _apply_stream_defaults(payload)
    if is_streaming_request(payload):
        _apply_streaming_options(payload)
    model = _apply_model_fallback(payload)
    if audiocpp_catalog.supports_clone(model):
        _apply_voice_ref_fallback(payload)
    else:
        payload.pop("voice", None)
        payload.pop("voice_ref", None)
        payload.pop("reference_text", None)
    if model in cfg.BREEZE_MODELS:
        tts_text_processing.apply_breeze_tone(payload)
    if not isinstance(payload.get("input"), str):
        return None
    cleaned, _ = tts_text_processing.clean_text(payload)
    if cleaned is None:
        return None
    payload["input"] = cleaned
    if preset := _preset_for(model):
        if preset.prepend:
            payload["input"] = preset.prepend + cleaned
        _apply_request_options(payload, preset, model)
    return payload


def _apply_stream_defaults(payload: Payload) -> None:
    """
    - With native streaming enabled, requests use the configured PCM transport unless the client
      explicitly sent stream:false
    - A streamed request always carries response_format=pcm, since audio.cpp accepts no other
      format for streaming; a client-supplied value can never leave it inconsistent
    """
    selected = str(payload.get("model") or cfg.AUDIOCPP_SERVICE.model)
    preset = _preset_for(selected) if selected in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS else None
    if payload.get("stream") is False:
        payload.pop("stream_format", None)
    if preset and not preset.streaming_supported:
        if is_streaming_request(payload):
            raise audiocpp_catalog.ComparisonSelectionError("This model supports Complete WAV only; disable streaming")
        payload["stream"] = False
        payload.setdefault("response_format", "wav")
        return
    if cfg.AUDIOCPP_SERVICE.streaming_enabled and payload.get("stream") is not False:
        payload["stream"] = True
        payload.setdefault("stream_format", cfg.AUDIOCPP_SERVICE.streaming.transport.value)
        payload["response_format"] = "pcm"


def _apply_streaming_options(payload: Payload) -> None:
    """
    - Configured streaming tuning values; None means "use the server default"
    - Client-sent options win
    """
    options = payload.setdefault("options", {})
    if not isinstance(options, dict):
        return
    settings = cfg.AUDIOCPP_SERVICE.streaming
    for key in ("stream_frames_per_event", "stream_lookahead_margin", "stream_chunk_policy"):
        value = getattr(settings, key)
        if value is not None:
            options.setdefault(key, value)


def _preset_for(model: str):
    return cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(model))


def _apply_model_fallback(payload: Payload) -> str:
    """
    - Fall back to the default model if missing or not one audio.cpp knows about
    - audio.cpp hard-errors on a missing/unknown model, it does NOT default
      this itself
    """
    model = str(payload.get("model", ""))
    if model not in cfg.AUDIOCPP_PROXY_ACCEPTED_MODELS:
        model = str(cfg.AUDIOCPP_SERVICE.model)
        payload["model"] = model
    return model


def _apply_voice_ref_fallback(payload: Payload) -> None:
    """
    - Resolve the request voice to a reference, or use the configured default
    - The voice name must match a clone voice exactly - use one name everywhere
    - Unknown names fall back to the default, annotated in the request log line
    """
    default_voice = cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value
    requested = str(payload.get("voice", "")).strip()
    voice = requested if requested in cfg.AUDIOCPP_PROXY_CLONE_VOICES else default_voice
    if requested and voice != requested:
        payload["_voice_fallback"] = requested  # surfaced in the request log line

    candidates = [voice] if voice == default_voice else [voice, default_voice]
    for name in candidates:
        if ref := audiocpp_catalog.resolve_voice_ref(name):
            payload["voice"] = name
            payload["voice_ref"], payload["reference_text"] = ref
            return

    payload["voice"] = default_voice
    payload.pop("voice_ref", None)
    payload.pop("reference_text", None)
    if cfg.AUDIOCPP_PROXY_CLONE_VOICES:
        # - with no local voice references at all, the model's own voice is the intended default
        print(f"[audiocpp-proxy] warning: no clone files found for {candidates}")


def _apply_request_options(payload: Payload, preset, model: str) -> None:
    options = payload.setdefault("options", {})
    if not isinstance(options, dict):
        return
    streaming_keys = {"stream_frames_per_event", "stream_lookahead_margin", "stream_chunk_policy"}
    for key, value in audiocpp_catalog.server_request_defaults(model).items():
        if key in streaming_keys and not is_streaming_request(payload):
            continue
        options.setdefault(key, value)
    for k, v in preset.request_options.items():
        options.setdefault(k, v)


def _trigger_audiocpp_preload(on_success: Callable[[], None] | None = None) -> None:
    # - Warm the exact clone path rather than an unconditioned request
    # - Breeze can retain the first reference context it sees in its model session
    default_voice = cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value
    payload: Payload = {"input": "hello", "model": str(cfg.AUDIOCPP_SERVICE.model), "voice": default_voice}
    if ref := audiocpp_catalog.resolve_voice_ref(default_voice):
        payload["voice_ref"], payload["reference_text"] = ref

    trigger_preload(
        enabled=cfg.AUDIOCPP_SERVICE.warmup,
        tag="audiocpp-proxy",
        url=f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.port}/v1/audio/speech",
        payload=payload,
        on_success=on_success,
        ready_url=ready_url("audiocpp", cfg.AUDIOCPP_SERVICE.internal_port),
    )


def _log_settings() -> None:
    """
    - Startup banner: every proxy-relevant settings group, on or off
    """
    tag = "audiocpp-proxy"
    print_settings(
        tag,
        "vocal events",
        tts_text_processing.BREEZE_VOCAL_EVENTS,
        off=not tts_text_processing.BREEZE_VOCAL_EVENTS.enabled,
    )
    print_settings(
        tag,
        "tones",
        tts_text_processing.BREEZE_TONES,
        off=not (tts_text_processing.BREEZE_TONES.tags_enabled or tts_text_processing.BREEZE_TONES.default_enabled),
    )
    print_settings(tag, "cleanup", cfg.SHARED_TTS_TEXT_CLEANUP)
    model = str(cfg.AUDIOCPP_SERVICE.model)
    if preset := _preset_for(model):
        print_settings(tag, f"preset[{model}]", preset)


def launch_proxy(extra_args: list[str] | None = None) -> None:
    forwarded = list(sys.argv[1:] if extra_args is None else extra_args)
    prepare_service_port(cfg.AUDIOCPP_SERVICE.port, "AudioCpp Proxy")
    _log_settings()
    before = get_gpu_memory_snapshot()
    print(f"[audiocpp-proxy] native audio streaming: {cfg.AUDIOCPP_SERVICE.streaming_enabled}")
    process = audiocpp.launch(port=cfg.AUDIOCPP_SERVICE.internal_port, extra_args=forwarded, report_vram=False)

    upstream = f"http://127.0.0.1:{cfg.AUDIOCPP_SERVICE.internal_port}"

    _trigger_audiocpp_preload(lambda: report_vram_usage_async("audio.cpp", process.pid, before))

    service = cfg.AUDIOCPP_SERVICE
    source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
    lifecycle = OwnedBackendLifecycle(
        process,
        lambda: audiocpp.launch(
            port=service.internal_port,
            extra_args=forwarded,
            report_vram=False,
            mode=cfg.ConsoleTerminalLaunchMode.MERGE,
        ),
        ready_url("audiocpp", cfg.AUDIOCPP_SERVICE.internal_port),
        lambda: audio_cfg.read(source),
    )

    def reload_settings() -> None:
        reload_proxy_configuration(service, "AUDIOCPP_SERVICE")
        importlib.reload(tts_text_processing)

    controller = ProxyRestartController(
        {"backend": lifecycle.restart, "proxy": reload_settings},
        {"backend": [source, Path(cfg.__file__)], "proxy": [Path(cfg.__file__), Path(tts_text_processing.__file__)]},
    )
    run_tts_json_proxy(
        service,
        upstream,
        transform=_transform,
        tag="audiocpp-proxy",
        restart_controller=controller,
        test_page_redirect=f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.port}/test/",
    )


def main() -> None:
    launch_proxy(extra_args=sys.argv[1:])


if __name__ == "__main__":
    main()
