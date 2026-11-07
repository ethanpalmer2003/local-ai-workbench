"""Estimate VRAM usage for configured GGUF models without launching them.

- Weights VRAM: GGUF file size (full GPU offload)
- KV cache: computed from each GGUF's own metadata (layers, kv heads, key/value
  lengths) at the launcher's context size
  - SWA models (gemma family): sliding-window layers only cache the window
    (5 SWA : 1 full layer pattern)
  - quantkv q8_0 (kobold) -> ~1 byte per element; f16 -> 2
- Compute buffer: rough flat allowance (batch-size dependent)
- These are CALCULATIONS from file size + header metadata, except the compute
  allowance which is an ESTIMATE
- Run from C:/AI: python -m scripts.tests.cases.koboldcpp.kobold_vram_estimate
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, cast

from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.config.models.gguf_metadata import read_metadata
from scripts.launchers import launcher_config as cfg
from scripts.tests.shared.timing import timed

# - audio.cpp has no LLM-style ctx; breeze's model_spec (read from the GGUF)
#   defines session memory as graph_arena_mb=1024 MiB default + reference
#   cache; generation is capped by max_tokens=1500 acoustic frames, not a
#   KV window
AUDIOCPP_CTX_PLACEHOLDER = 0
AUDIOCPP_COMPUTE_MIB = 1024.0  # graph_arena_mb default from model_spec
COMPUTE_ALLOWANCE_MIB = 400.0


def kv_cache_mib(meta: dict[str, Any], ctx: int, bytes_per_elem: float) -> float:
    arch = str(meta.get("general.architecture", "llama"))
    layers = int(meta.get(f"{arch}.block_count", 0))
    # - GQA models expose head_count_kv; MHA models only have head_count
    kv_heads = int(meta.get(f"{arch}.attention.head_count_kv", meta.get(f"{arch}.attention.head_count", 0)) or 0)
    key_len = int(meta.get(f"{arch}.attention.key_length", 0))
    value_len = int(meta.get(f"{arch}.attention.value_length", 0))
    if not (layers and kv_heads and key_len and value_len):
        return 0.0

    # - SWA models (gemma family): most layers only cache the sliding window;
    #   gemma pattern is 5 SWA layers : 1 full-attention layer
    swa = int(meta.get(f"{arch}.attention.sliding_window", 0) or 0)
    if swa and swa < ctx:
        swa_layers = layers * 5 // 6
        full_layers = layers - swa_layers
        tokens = swa_layers * swa + full_layers * ctx
    else:
        tokens = layers * ctx

    # K + V across all layers
    elems = tokens * kv_heads * (key_len + value_len)
    return elems * bytes_per_elem / (1024 * 1024)


def report(label: str, path: Path, ctx: int, bytes_per_elem: float, compute_mib: float = COMPUTE_ALLOWANCE_MIB) -> None:
    if not path.is_file():
        print(f"{label:28} MISSING: {path.name}")
        return
    meta = read_metadata(path)
    weights_gib = path.stat().st_size / (1024**3)
    kv = kv_cache_mib(meta, ctx, bytes_per_elem) if ctx else 0.0
    total = weights_gib + kv / 1024 + compute_mib / 1024
    print(f"{label:28} {weights_gib:9.2f} {kv:8.0f} {total:14.2f}")


def collect(kobold_ctx: int, kobold_bytes_per_elem: float) -> dict[str, dict[str, float]]:
    """One entry per model: {weights_gib, kv_mib, total_gib, ctx}"""
    out: dict[str, dict[str, float]] = {}
    for name, path in cfg.KOBOLDCPP_MODELS.items():
        if not path.is_file():
            continue
        meta = read_metadata(path)
        kv = kv_cache_mib(meta, kobold_ctx, kobold_bytes_per_elem)
        weights = path.stat().st_size / 1024**3
        out[name] = {
            "weights_gib": round(weights, 3),
            "kv_mib": round(kv, 1),
            "total_gib": round(weights + kv / 1024 + COMPUTE_ALLOWANCE_MIB / 1024, 3),
            "ctx": kobold_ctx,
        }
    for label, path in _audiocpp_models():
        if not path.is_file():
            continue
        weights = path.stat().st_size / 1024**3
        out[label] = {
            "weights_gib": round(weights, 3),
            "kv_mib": 0.0,
            "total_gib": round(weights + AUDIOCPP_COMPUTE_MIB / 1024, 3),
            "ctx": 0,
        }
    return out


def _cache_path() -> Path:
    return project_cfg.CACHE_DIR / "kobold_vram_estimate" / "vram_estimates.json"


def refresh_cache() -> None:
    kobold_ctx = int(cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["contextsize"]))
    quantkv = str(cfg.KOBOLDCPP_KCPPS_ARGS.get("quantkv", "f16"))
    kobold_bytes_per_elem = 1.0 if quantkv == "q8_0" else 2.0

    models = collect(kobold_ctx, kobold_bytes_per_elem)
    data = {"updated": time.strftime("%Y-%m-%d %H:%M"), "kobold_ctx": kobold_ctx, "quantkv": quantkv, "models": models}
    cache = _cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"cached {len(models)} models -> {cache}")


def lookup(name: str) -> None:
    cache = _cache_path()
    if not cache.is_file():
        print(f"no cache at {cache}; run with --refresh first")
        return
    data: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
    models = cast(dict[str, dict[str, float]], data["models"])
    # - substring match wins over exact key so "cydonia"/"breeze" work
    hits = [k for k in models if name.lower() in k.lower()] or [k for k in models if k.lower() in name.lower()]
    if not hits:
        print(f"'{name}' not in cache (updated {data['updated']})")
        return
    for key in hits[:3]:
        m = models[key]
        print(
            f"{key} (ctx={m['ctx']}): weights={m['weights_gib']:.2f} GiB, "
            f"kv={m['kv_mib']:.0f} MiB, total~={m['total_gib']:.2f} GiB"
        )


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--refresh":
        refresh_cache()
        return
    if args and args[0] == "--lookup":
        lookup(args[1])
        return

    kobold_ctx = int(cast(int, cfg.KOBOLDCPP_KCPPS_ARGS["contextsize"]))
    quantkv = str(cfg.KOBOLDCPP_KCPPS_ARGS.get("quantkv", "f16"))
    kobold_bytes_per_elem = 1.0 if quantkv == "q8_0" else 2.0

    print(f"== kobold models (ctx={kobold_ctx}, quantkv={quantkv}) ==\n")
    print(f"{'model':28} {'file GiB':>9} {'kv MiB':>8} {'est total GiB':>14}")
    for name, path in cfg.KOBOLDCPP_MODELS.items():
        report(name, path, kobold_ctx, kobold_bytes_per_elem)

    print(f"\n== audiocpp models (no ctx; graph_arena {AUDIOCPP_COMPUTE_MIB:.0f} MiB from model_spec) ==\n")
    print(f"{'model':28} {'file GiB':>9} {'kv MiB':>8} {'est total GiB':>14}")
    for label, model_path in _audiocpp_models():
        report(label, model_path, AUDIOCPP_CTX_PLACEHOLDER, 2.0, compute_mib=AUDIOCPP_COMPUTE_MIB)
    print("\n(use --refresh to cache, --lookup <name> to query)")


def _audiocpp_models() -> list[tuple[str, Path]]:
    """(label, path) per model entry in audiocpp's server.json"""

    server_json = Path(str(cfg.AUDIOCPP_SERVER_ARGS["config"]))
    data: Any = audio_cfg.read(server_json)
    models = cast(list[dict[str, Any]], data.get("models", []))
    return [(str(m["id"]), Path(str(m["path"]))) for m in models]


if __name__ == "__main__":
    with timed("koboldcpp/kobold_vram_estimate"):
        main()
