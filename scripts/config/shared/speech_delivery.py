"""One delivery preference order and persisted model-specific overrides for speech clients."""

import json
import threading

from scripts.config import project_config as project_cfg

# Default delivery for every speech surface: prefer true streaming, then sentence-level chunks, then one
# whole response. Each surface passes only the modes its framework supports, so the unsupported ones fall
# through, and a saved per-model override (state/shared/speech_delivery.json) replaces the default.
MODES = ('streaming', 'chunked', 'whole')
# True incremental streaming backends; ASR_CHUNKED adds VAD/segment backends that must never be called streaming.
ASR_STREAMING = ('audiocpp-nemotron', 'nemo-nemotron', 'parakeetcpp-nemotron-cpu')
ASR_CHUNKED = (*ASR_STREAMING, 'speechcpp-qwen-0.6b', 'whisper-vulkan', 'parakeetcpp-v3', 'audiocpp-cohere', 'granite-audio')
_LOCK = threading.RLock()


def tts_supported(streaming: bool) -> list[str]:
    """Ordered TTS modes: true streaming when available, then sentence chunks, then whole responses."""
    return ['streaming', 'chunked', 'whole'] if streaming else ['chunked', 'whole']


def state_path():
    return project_cfg.component('shared').state_dir / 'speech_delivery.json'


def overrides():
    with _LOCK:
        path = state_path()
        return json.loads(path.read_text(encoding='utf-8')).get('overrides', {}) if path.is_file() else {}


def save(stage, model, mode):
    if stage not in ('asr', 'llm', 'tts') or mode not in ('auto', *MODES):
        raise ValueError('Invalid delivery stage or mode')
    with _LOCK:
        values = overrides()
        key = f'{stage}:{model}'
        if mode == 'auto':
            values.pop(key, None)
        else:
            values[key] = mode
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'overrides': values}, indent=2), encoding='utf-8')
        temporary.replace(path)


def resolve(stage, model, supported, values=None):
    requested = (overrides() if values is None else values).get(f'{stage}:{model}', 'auto')
    order = MODES[MODES.index(requested):] if requested in MODES else MODES
    chain = [mode for mode in order if mode in supported]
    return {'model': model, 'requested': requested, 'supported': list(supported),
            'mode': chain[0] if chain else 'whole', 'fallbacks': chain[1:]}


def asr_plan(engine):
    supported = [mode for mode, available in (('streaming', engine in ASR_STREAMING),
                                             ('chunked', engine in ASR_CHUNKED), ('whole', True)) if available]
    return resolve('asr', engine, supported)
