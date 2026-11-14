"""Language practice with llama.cpp chat and independent ASR/TTS services."""

import subprocess
from typing import Any

from scripts.launchers import launch_util
from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.llamacpp import gemma_audio
from scripts.launchers.asr.shared import practice_models
from scripts.launchers.llamacpp import chat_models
from scripts.launchers.shared.services import native
from scripts.shared.wait import http_ready


def chat_command(model_id: str | None = None) -> list[str]:
    command = gemma_audio.command()
    command[command.index("-m") + 1] = str(chat_models.path(model_id))
    index = command.index("--mmproj")
    del command[index : index + 2]
    command[command.index("--port") + 1] = str(cfg.LLAMACPP_PRACTICE.internal_port)
    command[command.index("--alias") + 1] = "speech-workspace-chat"
    command.extend(["--reasoning-effort", "none", "--chat-template-kwargs", '{"enable_thinking":false}'])
    return command


def start_chat(model_id: str | None = None) -> subprocess.Popen[Any] | None:
    if launch_util.llama_server_running():
        print("Existing coding llama.cpp session retained; language practice uses its own port")
    command = chat_command(model_id)
    url = f"http://127.0.0.1:{cfg.LLAMACPP_PRACTICE.internal_port}"
    return native.start_server(
        command,
        (cfg.GEMMA_AUDIO_ASR.exe, chat_models.path(model_id)),
        cfg.LLAMACPP_PRACTICE.internal_port,
        "Practice chat",
        lambda: http_ready(url + "/health", strict=True),
        lambda: native.matches(command),
        component_key="llamacpp",
    )


def start_tts():
    """Legacy opt-in smoke entry; production stages use the lifecycle manager."""
    from scripts.launchers.audiocpp import model_management

    return model_management.start(
        {"backend": "vulkan", "threads": cfg.KOKORO_TTS.threads, "models": [practice_models.tts_spec()]},
        cfg.AUDIOCPP_SERVICE.internal_port,
    )


def main() -> None:
    from scripts.launchers.asr.shared import workspace

    workspace.main(start_chat)


if __name__ == "__main__":
    main()
