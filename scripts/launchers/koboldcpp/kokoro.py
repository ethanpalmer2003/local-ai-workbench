"""Opt-in native and external CPU Kokoro profiles for the Kobold workflow."""

import json

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp.kokoro import audio_command as audio_command
from scripts.launchers.audiocpp.kokoro import audio_environment as audio_environment
from scripts.launchers.shared.media.text_processing import clean_speech_payload


def selected() -> bool:
    return cfg.KOBOLDCPP_SERVICE.speech_engine != cfg.KoboldcppSpeechStartupEngine.CONFIGURED


def internal() -> bool:
    return cfg.KOBOLDCPP_SERVICE.speech_engine == cfg.KoboldcppSpeechStartupEngine.KOKORO_INTERNAL


def model_options() -> dict[str, object]:
    return {"ttsmodel": str(cfg.KOKORO_TTS.koboldcpp_model), "ttsthreads": cfg.KOKORO_TTS.threads} if internal() else {}


def speech_body(body: bytes) -> bytes:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Speech request must be a JSON object")
    clean_speech_payload(payload, language=cfg.KOKORO_TTS.language)
    payload.update(model=cfg.KOKORO_TTS_PACKAGES[cfg.KOKORO_TTS.audiocpp_package])
    payload.setdefault("voice", cfg.KOKORO_TTS.voice)
    for key in ("voice_ref", "reference_text", "instructions", "instruction"):
        payload.pop(key, None)
    if internal():
        payload.update(stream=False, response_format="wav")
        payload.pop("stream_format", None)
    else:
        options = payload.setdefault("options", {})
        if isinstance(options, dict):
            options.setdefault("language", cfg.KOKORO_TTS.language)
    return json.dumps(payload).encode("utf-8")
