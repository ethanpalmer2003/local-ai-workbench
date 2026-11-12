# Defaults

Every default has one owner in the repository; the input overlay overrides only local values. The overlay is `data/input/` (or `AI_INPUT_DIR`), never tracked.

| Default | Repository owner | Overlay override |
| --- | --- | --- |
| Ports, modes, enable flags, timeouts | [launcher_config.py](../../launchers/launcher_config.py) | none |
| Chat LLM, chat TTS model/voice/instruction | `KOBOLD_CHAT` in [launcher_config.py](../../launchers/launcher_config.py) | `chat.llm`, `chat.tts.*` |
| Image prompt, negative, sampler, size, seed, LoRAs | `SDCPP_PROXY_PROMPT` and `SDCPP_REQUEST_DEFAULTS` in [launcher_config.py](../../launchers/launcher_config.py) | `image.prompt`, `image.loras` |
| AudioCpp native models and session options | [audiocpp/server.json](../audiocpp/server.json) | none |
| Strata profile | [strata/](../strata/README.md) | none |
| Model identity, sources, restore selection | [models/catalog.json](../models/catalog.json) | `models.overlay.json` |
| ComfyUI paths and workflows | [comfyui/](../comfyui/README.md) | `video.prompt`, `video.negative` |
| Roots, component keys | [project_config.py](../project_config.py) | none |

- A personal value goes in the overlay's `defaults.yaml`; absence means the tracked default applies, so the same file works on any machine.
- A flag (`--model`, `--with-image`, `--config`) overrides one launch and never becomes configuration.
- Native JSON is edited directly; Python selects catalog ids and does not mirror native fields.

Overlay keys and their guards: [local inputs](INPUTS.md).
