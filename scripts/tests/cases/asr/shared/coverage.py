"""Explicit ASR coverage, including adapters that cannot yet enter resident rankings."""

import json

from scripts.config.asr.file_profiles import ASR_FILE_PROFILES


def coverage() -> list[dict[str, str]]:
    entries = {
        "nemo-speechcpp": (
            "resident_compare",
            "resident-validated",
            "Nemotron; offline HTTP validated, live latency pending",
        ),
        "speechcpp": (
            "resident_compare",
            "resident-validated",
            "Qwen 0.6B; offline HTTP validated, VAD/Realtime pending",
        ),
        "audiocpp-vulkan": ("resident_compare", "resident-validated", "Nemotron; persistent ASR HTTP"),
        "audiocpp-rocm": ("resident_compare", "resident-validated", "Nemotron; persistent ASR HTTP"),
        "parakeetcpp-cpu": ("resident_compare", "resident-validated", "110M English; VAD/streaming models pending"),
        "parakeetcpp-vulkan": (
            "resident_compare",
            "resident-validated",
            "110M English; verify backend log for device use",
        ),
        "whispercpp-vulkan-fa": ("resident_compare", "resident-validated", "Large-v3-turbo Q5; flash attention"),
        "koboldcpp-whisper": ("resident_compare", "resident-validated", "Embedded Whisper with same model"),
        "whispercpp-legacy-vulkan": (
            "whisper_embedded_compare",
            "disabled",
            "Retained community build, not a default test",
        ),
        "llamacpp-qwen-1.7b": ("resident_compare", "resident-validated", "Qwen main model plus audio projector"),
        "llamacpp-gemma-audio": ("resident_compare", "resident-validated", "Gemma E4B audio prompting"),
        "llamacpp-granite-5-2b": (
            "resident_compare",
            "resident-validated",
            "Granite Speech 2B plus projector; brief synthetic-English resident check, 2026-10-29",
        ),
        "audiocpp-cohere": (
            "resident_compare",
            "resident-validated",
            "Cohere Transcribe 2B; brief synthetic-English resident check, 2026-10-29",
        ),
        "koboldcpp-gemma-audio": ("gemma_audio_compare", "migrated-not-rerun", "Gemma E4B audio prompting"),
        "audiocpp-ming-audio-tiny": (
            "resident_compare",
            "resident-validated",
            "Offline ASR; expert offload; language prefix normalized; English clip validated",
        ),
        "audiocpp-qwen3": (
            "resident_compare",
            "resident-validated",
            "Qwen3-ASR 1.7B Q8_0 with explicit Vulkan session tuning; still slower than llama.cpp on the same model",
        ),
        "handy": ("none", "manual", "GUI dictation, not a comparable HTTP/CLI backend"),
        "parakeetcpp-v3": (
            "resident_compare",
            "resident-validated",
            "0.6B v3 Q8; Vulkan offline HTTP and Silero file VAD pass",
        ),
        "parakeetcpp-nemotron-streaming": (
            "resident_compare",
            "resident-validated",
            "Vulkan offline HTTP passes; CPU file streaming passes; installed Vulkan streaming crashes",
        ),
    }
    for key, profile in ASR_FILE_PROFILES.items():
        if key not in entries:
            runner = "resident_compare" if profile.server_arguments is not None else "file_diagnostic"
            entries[key] = (runner, "unreviewed", "Configured file profile; validation status not recorded")
    return [
        {"engine": key, "runner": runner, "status": status, "detail": detail}
        for key, (runner, status, detail) in entries.items()
    ]


if __name__ == "__main__":
    print(json.dumps(coverage(), indent=2))
