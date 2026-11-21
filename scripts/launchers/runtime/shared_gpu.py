"""Explicit co-resident GPU policy; standalone launches do not select it."""

import json
from pathlib import Path

from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg

IMAGE_ARGS = ("--backend", "Vulkan0,te=cpu", "--vae-tiling", "--vae-tile-size", "512x512")
KOBOLDCPP_MODEL_ARGS = {"koboldcpp/TheDrummer_Rocinante-X-12B-v1-IQ4_XS": {"gpulayers": 16}}
AUDIO_SESSION_OPTIONS = {
    "fish_drama3": {"fish_drama3.cpu_expert_layers": 40},
    "ming3_audio": {"ming3_audio.disk_experts": True, "ming3_audio.pin_experts": False},
}


def audio_config(source: Path, port: int) -> Path:
    """Derive a native server config because its CLI has no session-option override."""
    config = audio_cfg.read(source)
    for model in config["models"]:
        options = AUDIO_SESSION_OPTIONS.get(model.get("family"))
        if options:
            model["session_options"] = {**model.get("session_options", {}), **options}
        path = Path(model["path"])
        if not path.is_absolute():
            model["path"] = str((source.parent / path).resolve())
    target = project_cfg.component("audiocpp").generated_dir / f"shared-{port}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return target
