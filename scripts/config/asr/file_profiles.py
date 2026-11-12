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
    session_options: dict[str, object] | None = None
    request_options: dict[str, object] | None = None


def weight(label: str) -> str:
    return str(model_cfg.path(label))


def binary(component: str, relative: str) -> Path:
    return project_cfg.component(component).framework_dir / relative


def options(flag: str, values: dict[str, object]) -> tuple[str, ...]:
    """Render AudioCpp key/value CLI options from the same mapping the generated config uses."""

    def text(value: object) -> str:
        return str(value).lower() if isinstance(value, bool) else str(value)

    return tuple(part for key, value in values.items() for part in (flag, f"{key}={text(value)}"))


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

MING_SESSION: dict[str, object] = {
    "ming3_audio.disk_experts": True,
    "ming3_audio.pin_experts": False,
    "ming3_audio.expert_cache_size": 8,
    "ming3_audio.disk_expert_read_threads": 4,
}
MING_REQUEST: dict[str, object] = {"max_tokens": 96, "enable_thinking": False}

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
        *options("--request-option", MING_REQUEST),
        *options("--session-option", MING_SESSION),
    ),
    ("audiocpp/ming3-audio-tiny-q4_k",),
    {"offline": ()},
    languages=("auto",),
    streaming_kind="offline prompted transcription; resident adapter normalizes the language label",
    server_arguments=("--config", "{config}", "--port", "{port}", "--no-ui"),
    server_executable=binary("audiocpp", "vulkan/audiocpp_server.exe"),
    audio_family="ming3_audio",
    session_options=MING_SESSION,
    request_options=MING_REQUEST,
)

# AudioCpp's fastest Qwen session settings; the spec's cuda_perf preset is CUDA-gated, so the
# equivalent Vulkan options are selected explicitly. Faster on both corpus clips with unchanged text.
QWEN3_SESSION: dict[str, object] = {
    "attention": "flash",
    "packed_projections": True,
    "kv_cache_type": "f16",
    "kv_cache_alignment": 256,
    "offline_batch_size": 2,
}
ASR_FILE_PROFILES["audiocpp-qwen3"] = FileAsrProfile(
    "audiocpp",
    binary("audiocpp", "vulkan/audiocpp_cli.exe"),
    (
        "--task",
        "asr",
        "--family",
        "qwen3_asr",
        "--model",
        weight("asr/audiocpp/qwen3-asr-1.7b-q8_0"),
        "--backend",
        "vulkan",
        "--audio",
        "{input}",
        "--language",
        "{language}",
        *options("--session-option", QWEN3_SESSION),
    ),
    ("asr/audiocpp/qwen3-asr-1.7b-q8_0",),
    {"offline": (), "streaming": ("--mode", "streaming")},
    streaming_kind="native streaming Qwen3 checkpoint; separate AudioCpp GGUF from the llama.cpp file",
    server_arguments=("--config", "{config}", "--port", "{port}", "--no-ui"),
    server_executable=binary("audiocpp", "vulkan/audiocpp_server.exe"),
    audio_family="qwen3_asr",
    session_options=QWEN3_SESSION,
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
