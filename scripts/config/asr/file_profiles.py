"""File/live ASR CLI profiles; model identities and install paths have one owner."""

from dataclasses import dataclass
from pathlib import Path

from scripts.config import models as model_cfg
from scripts.config import project_config as project_cfg


@dataclass(frozen=True)
class FileAsrProfile:
    component: str
    executable: Path
    arguments: tuple[str, ...]
    models: tuple[str, ...]
    modes: dict[str, tuple[str, ...]]
    default_mode: str = "offline"
    languages: tuple[str, ...] = ()
    streaming_kind: str = "offline"
    server_arguments: tuple[str, ...] | None = None
    server_executable: Path | None = None
    environment_overrides: tuple[tuple[str, str], ...] = ()
    audio_family: str | None = None
    mode_executables: dict[str, Path] | None = None
    mode_environments: dict[str, tuple[tuple[str, str], ...]] | None = None


def weight(label: str) -> str:
    return str(model_cfg.path(label))


def binary(component: str, relative: str) -> Path:
    return project_cfg.component(component).framework_dir / relative


ASR_FILE_PROFILES = {
    "audiocpp-cohere": FileAsrProfile(
        "asr/audiocpp",
        binary("audiocpp", "vulkan/audiocpp_cli.exe"),
        (
            "--task",
            "asr",
            "--family",
            "cohere_asr",
            "--model",
            weight("asr/audiocpp/cohere-transcribe-03-2026-q8_0"),
            "--audio",
            "{input}",
            "--language",
            "{language}",
        ),
        ("asr/audiocpp/cohere-transcribe-03-2026-q8_0",),
        {"offline": ()},
        server_arguments=("--config", "{config}", "--port", "{port}", "--no-ui"),
        server_executable=binary("audiocpp", "vulkan/audiocpp_server.exe"),
        audio_family="cohere_asr",
    ),
    "nemo-speechcpp": FileAsrProfile(
        "asr/nemo-speechcpp",
        binary("asr/nemo-speechcpp", "vulkan/bin/nemo-speech.exe"),
        (
            "transcribe",
            "{input}",
            "--model",
            weight("asr/nemo-speechcpp/nemotron-3.5-q8_0"),
            "--backend",
            "vulkan",
            "--language",
            "{language}",
        ),
        ("asr/nemo-speechcpp/nemotron-3.5-q8_0",),
        {"offline": (), "streaming": ("--stream",), "live": ("--live",)},
        streaming_kind="cache-aware Nemotron; recorded chunks or microphone",
        server_arguments=("serve", "--asr-model", "{model}", "--backend", "vulkan", "--port", "{port}", "--no-ui"),
    ),
    "speechcpp": FileAsrProfile(
        "asr/speechcpp",
        binary("asr/speechcpp", "vulkan/speech.exe"),
        (
            "asr",
            weight("asr/speechcpp/qwen3-asr-0.6b-q8_0"),
            "--device",
            "gpu",
            "--threads",
            "4",
            "--language",
            "{language}",
            "{input}",
        ),
        ("asr/speechcpp/qwen3-asr-0.6b-q8_0", "asr/speechcpp/silero-vad"),
        {"offline": (), "live": ("--vad", weight("asr/speechcpp/silero-vad"), "--live")},
        streaming_kind="VAD-delimited Qwen utterances; not a native streaming Qwen model",
        server_arguments=("serve", "{model}", "--device", "gpu", "--threads", "4", "--port", "{port}"),
    ),
}

for variant, backend in (("vulkan", "vulkan"), ("rocm", "hip")):
    ASR_FILE_PROFILES["audiocpp-" + variant] = FileAsrProfile(
        "audiocpp",
        binary("audiocpp", variant + "/audiocpp_cli.exe"),
        (
            "--task",
            "asr",
            "--family",
            "nemotron_asr",
            "--model",
            weight("audiocpp/nemotron-3.5-q8_0"),
            "--backend",
            backend,
            "--audio",
            "{input}",
            "--language",
            "{language}",
        ),
        ("audiocpp/nemotron-3.5-q8_0",),
        {"offline": (), "streaming": ("--mode", "streaming")},
        streaming_kind="cache-aware Nemotron; recorded chunks; separate AudioCpp GGUF",
        server_arguments=("--config", "{config}", "--port", "{port}", "--no-ui"),
        server_executable=binary("audiocpp", variant + "/audiocpp_server.exe"),
        audio_family="nemotron_asr",
    )

ASR_FILE_PROFILES["audiocpp-ming-audio-tiny"] = FileAsrProfile(
    "audiocpp",
    binary("audiocpp", "vulkan/audiocpp_cli.exe"),
    (
        "--task",
        "asr",
        "--family",
        "ming3_audio",
        "--model",
        weight("audiocpp/ming3-audio-tiny-q4_k"),
        "--backend",
        "vulkan",
        "--audio",
        "{input}",
        "--request-option",
        "max_tokens=96",
        "--request-option",
        "enable_thinking=false",
        "--session-option",
        "ming3_audio.disk_experts=true",
        "--session-option",
        "ming3_audio.pin_experts=false",
        "--session-option",
        "ming3_audio.expert_cache_size=8",
    ),
    ("audiocpp/ming3-audio-tiny-q4_k",),
    {"offline": ()},
    languages=("auto",),
    streaming_kind="offline prompted transcription; resident adapter normalizes the language label",
    server_arguments=("--config", "{config}", "--port", "{port}", "--no-ui"),
    server_executable=binary("audiocpp", "vulkan/audiocpp_server.exe"),
    audio_family="ming3_audio",
)

for key, label, streaming in (
    ("parakeetcpp-v3", "parakeet-tdt-0.6b-v3-q8_0", False),
    ("parakeetcpp-nemotron-streaming", "nemotron-3.5-streaming-q8_0", True),
):
    vad = ("--vad", "--vad-model", weight("asr/parakeetcpp/silero-vad-f16"))
    ASR_FILE_PROFILES[key] = FileAsrProfile(
        "asr/parakeetcpp",
        binary("asr/parakeetcpp", "vulkan/parakeet-cli.exe"),
        (
            "transcribe",
            "--model",
            weight("asr/parakeetcpp/" + label),
            "--input",
            "{input}",
            "--threads",
            "4",
            *(("--lang", "{language}") if streaming else ()),
        ),
        ("asr/parakeetcpp/" + label, "asr/parakeetcpp/silero-vad-f16"),
        {"offline": vad, **({"streaming": ("--stream",)} if streaming else {})},
        languages=() if streaming else ("auto",),
        streaming_kind="cache-aware Nemotron" if streaming else "offline multilingual Parakeet v3",
        server_arguments=("--model", "{model}", "--port", "{port}", "--threads", "4"),
        server_executable=binary("asr/parakeetcpp", "vulkan/parakeet-server.exe"),
        environment_overrides=(("PARAKEET_DEVICE", "Vulkan0"),),
        mode_executables={"streaming": binary("asr/parakeetcpp", "cpu/parakeet-cli.exe")} if streaming else None,
        mode_environments={"streaming": (("PARAKEET_DEVICE", "cpu"),)} if streaming else None,
    )
