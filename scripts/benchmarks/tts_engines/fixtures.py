"""Same-voice inputs shared by resident TTS adapters."""

from scripts.config import models as model_cfg
from scripts.config import project_config as cfg

TEXT = (
    "Good morning. How are you today? I am practicing English, and I would like to speak more clearly and confidently."
)
VOICE = cfg.component("tts/piper").models_dir / "lessac-medium/en_US-lessac-medium.onnx"
TOKEN_PATH = VOICE.parent / "tokens.txt"
LEXICON = cfg.component("tts/sherpa-onnx").models_dir / "lexicon-en-us.txt"


def voice_assets(profile):
    if profile == "kokoro-v1.0-int8":
        prefix = "tts/sherpa-onnx/kokoro-v1.0-int8/"
        return model_cfg.path(prefix + "model"), model_cfg.path(prefix + "tokens"), model_cfg.path(prefix + "lexicon")
    if profile == "lessac-high":
        return model_cfg.path("tts/piper/lessac-high/model"), None, None
    return VOICE, TOKEN_PATH, LEXICON
