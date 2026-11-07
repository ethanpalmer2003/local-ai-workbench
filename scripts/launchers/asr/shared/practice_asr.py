"""Selectable ASR profiles; separate from TTS configuration to keep adapters acyclic."""

from pathlib import Path
from typing import Any

from scripts.config import models
from scripts.launchers import launcher_config as cfg


def asr_models() -> list[dict[str, Any]]:
    from scripts.launchers.asr import selector
    rows = []
    labels = {
        cfg.AsrStartupEngine.COHERE: ('AudioCpp', 'Cohere Transcribe 2B'),
        cfg.AsrStartupEngine.GRANITE: ('llama.cpp', 'Granite Speech 5.0 2B'),
        cfg.AsrStartupEngine.AUDIOCPP: ('AudioCpp', 'Nemotron 3.5 Streaming 0.6B'),
        cfg.AsrStartupEngine.NEMO: ('NeMo-Speech.cpp', 'Nemotron 3.5 Streaming 0.6B'),
        cfg.AsrStartupEngine.PARAKEET_STREAM: ('parakeet.cpp (CPU streaming)', 'Nemotron 3.5 Streaming 0.6B'),
        cfg.AsrStartupEngine.PARAKEET_V3: ('parakeet.cpp (Vulkan)', 'Parakeet TDT v3 0.6B'),
        cfg.AsrStartupEngine.SPEECHCPP: ('speech.cpp', 'Qwen3-ASR 0.6B'),
        cfg.AsrStartupEngine.WHISPER_VULKAN: ('whisper.cpp', 'Whisper large-v3-turbo Q5'),
        cfg.AsrStartupEngine.QWEN3_ASR: ('llama.cpp', 'Qwen3-ASR 1.7B'),
        cfg.AsrStartupEngine.GEMMA_AUDIO: ('llama.cpp', 'Gemma 4 E4B audio'),
    }
    for engine, (framework, label) in labels.items():
        path = selector.model(engine)
        key = next((model.label for model in models.MODELS if model.path == path), None)
        command = selector.backend(engine).command()
        required = [path, Path(command[0])]
        if '--mmproj' in command:
            required.append(Path(command[command.index('--mmproj') + 1]))
        if engine == cfg.AsrStartupEngine.PARAKEET_STREAM:
            required.append(cfg.PARAKEETCPP_STREAM_LIBRARY)
        available = all(item.is_file() for item in required)
        rows.append({'id': engine.value, 'engine': engine.value, 'framework': framework, 'label': label,
                     'model_id': key, 'available': available, 'reason': '' if available else 'Model or framework is not installed'})
    return rows


