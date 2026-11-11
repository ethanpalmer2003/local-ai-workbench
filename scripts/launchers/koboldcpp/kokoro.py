"""Opt-in native and external AudioCpp speech profiles for the Kobold workflow."""

import json
from pathlib import Path

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp.kokoro import audio_command as audio_command_impl
from scripts.launchers.audiocpp.kokoro import audio_environment as audio_environment
from scripts.launchers.shared.media.text_processing import clean_speech_payload


def selected() -> bool:
    return cfg.KOBOLDCPP_SERVICE.speech_engine != cfg.KoboldcppSpeechStartupEngine.CONFIGURED


def internal() -> bool:
    return cfg.KOBOLDCPP_SERVICE.speech_engine == cfg.KoboldcppSpeechStartupEngine.KOKORO_INTERNAL


def practice_spec() -> dict[str, object]:
    """The selected practice TTS model: one source for its id, family and weights."""
    from scripts.launchers.asr.shared import practice_models

    return practice_models.tts_spec()


def family() -> str:
    return str(practice_spec()["family"])


def model_options() -> dict[str, object]:
    """Native KoboldCpp loads the installed GGUF; the voice travels with each request."""
    return {"ttsmodel": str(practice_spec()["path"]), "ttsthreads": cfg.KOKORO_TTS.threads} if internal() else {}


def audio_command(port: int, config_path: Path | None = None, *, backend: str = "cpu") -> list[str]:
    return audio_command_impl(port, config_path, backend=backend, spec=practice_spec())


def speech_body(body: bytes) -> bytes:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Speech request must be a JSON object")
    clean_speech_payload(payload, language=cfg.KOKORO_TTS.language)
    payload.update(model=str(practice_spec()["id"]))
    for key in ("voice_ref", "reference_text", "instructions", "instruction"):
        payload.pop(key, None)
    options = payload.setdefault("options", {})
    if family() == "supertonic":
        # - Preset voices and the language from the text, no locale field.
        # - Native KoboldCpp reads the top-level voice; AudioCpp accepts either, and the proxy
        #   strips voice for non-clone models, so the external route keeps the request option.
        payload.pop("voice", None)
        if isinstance(options, dict):
            options.pop("voice_id", None)
        if internal():
            payload["voice"] = cfg.SUPERTONIC_TTS.voice
        elif isinstance(options, dict):
            options["voice_id"] = cfg.SUPERTONIC_TTS.voice
    else:
        payload.setdefault("voice", cfg.KOKORO_TTS.voice)
        if isinstance(options, dict):
            options.setdefault("language", cfg.KOKORO_TTS.language)
    if internal():
        payload.update(stream=False, response_format="wav")
        payload.pop("stream_format", None)
    return json.dumps(payload).encode("utf-8")
