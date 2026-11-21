"""Speech endpoint the Kobold workflow serves: the selected practice TTS model and its request body."""

import json
from pathlib import Path

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp.tts_server import audio_command as audio_command_impl
from scripts.launchers.audiocpp.tts_server import audio_environment as audio_environment
from scripts.launchers.shared.media.text_processing import clean_speech_payload


def selected() -> bool:
    return cfg.KOBOLDCPP_SERVICE.speech_engine != cfg.KoboldcppSpeechStartupEngine.CONFIGURED


def practice_spec() -> dict[str, object]:
    """The selected practice TTS model: one source for its id, family and weights."""
    from scripts.launchers.asr.shared import practice_models

    return practice_models.tts_spec()


def family() -> str:
    return str(practice_spec()["family"])


def audio_command(port: int, config_path: Path | None = None, *, backend: str = "cpu") -> list[str]:
    return audio_command_impl(port, practice_spec(), config_path, backend=backend)


def speech_body(body: bytes) -> bytes:
    """Re-encode a page request for the AudioCpp proxy that serves the selected model."""
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Speech request must be a JSON object")
    clean_speech_payload(payload, language=cfg.AUDIOCPP_SPEECH.language)
    payload.update(model=str(practice_spec()["id"]))
    for key in ("voice_ref", "reference_text", "instructions", "instruction"):
        payload.pop(key, None)
    options = payload.setdefault("options", {})
    if family() == "supertonic":
        # - Supertonic takes a preset voice id and reads the language from the text; the proxy
        #   strips a top-level voice for non-clone models, so the request option carries it.
        payload.pop("voice", None)
        if isinstance(options, dict):
            options["voice_id"] = cfg.SUPERTONIC_TTS.voice
    return json.dumps(payload).encode("utf-8")
