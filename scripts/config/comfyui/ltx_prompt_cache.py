"""Local disk cache for the workflow's direct GGUF text encoder."""

import hashlib
import json
import os
import uuid
from importlib import import_module
from pathlib import Path
from typing import Any

CACHE_DIR = Path(
    os.environ.get("LTX_CONDITIONING_CACHE")
    or str(Path(__file__).resolve().parents[2] / "state" / "cache" / "ltx-conditioning")
)


def cache_file(text: str, prompt: dict[str, Any], unique_id: str) -> Path:
    folder_paths = import_module("folder_paths")

    source = prompt[str(unique_id)]["inputs"]["clip"][0]
    loader = prompt[str(source)]
    if loader["class_type"] not in {"CLIPLoaderGGUF", "CLIPLoaderGGUFDynamicVRAM"}:
        raise ValueError("Prompt caching requires a direct GGUF CLIP loader; disable the cache for patched encoders")
    inputs = loader["inputs"]
    model = Path(folder_paths.get_full_path_or_raise("clip", inputs["clip_name"]))
    stat = model.stat()
    if folder_paths.__file__ is None:
        raise RuntimeError("ComfyUI folder_paths has no file location")
    comfy_root = Path(folder_paths.__file__).parent
    version_file = comfy_root / ".last_update_hash"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"
    signature = {
        "format": 1,
        "text": text,
        "loader": loader,
        "model": str(model.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "comfy_version": version,
    }
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.pt"


def cpu_conditioning(value: Any) -> Any:
    import torch

    if isinstance(value, torch.Tensor):
        return value.detach().to("cpu").contiguous()
    if isinstance(value, dict):
        return {key: cpu_conditioning(item) for key, item in value.items()}
    if isinstance(value, list):
        return [cpu_conditioning(item) for item in value]
    if isinstance(value, tuple):
        return tuple(cpu_conditioning(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Unsupported conditioning metadata: {type(value).__name__}")


class LocalLTXCachedTextEncode:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "clip": ("CLIP", {"lazy": True}),
                "text": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "cache_enabled": ("BOOLEAN", {"default": True}),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "conditioning/local"

    @classmethod
    def IS_CHANGED(
        cls, clip: Any, text: str, cache_enabled: bool, prompt: dict[str, Any], unique_id: str
    ) -> str | float:
        return cache_file(text, prompt, unique_id).stem if cache_enabled else float("nan")

    def check_lazy_status(
        self, clip: Any, text: str, cache_enabled: bool, prompt: dict[str, Any], unique_id: str
    ) -> list[str]:
        if cache_enabled and cache_file(text, prompt, unique_id).is_file():
            return []
        return ["clip"] if clip is None else []

    def encode(self, clip: Any, text: str, cache_enabled: bool, prompt: dict[str, Any], unique_id: str) -> tuple[Any]:
        import torch

        path = cache_file(text, prompt, unique_id) if cache_enabled else None
        if path is not None and path.is_file():
            print("[LTX prompt cache] Hit; text encoder skipped")
            return (torch.load(path, map_location="cpu", weights_only=True),)
        if clip is None:
            raise RuntimeError("Prompt cache disappeared before execution; queue again to rebuild it")
        conditioning = clip.encode_from_tokens_scheduled(clip.tokenize(text))
        if path is None:
            return (conditioning,)
        conditioning = cpu_conditioning(conditioning)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        torch.save(conditioning, temporary)
        temporary.replace(path)
        print("[LTX prompt cache] Saved CPU conditioning")
        return (conditioning,)


NODE_CLASS_MAPPINGS = {"LocalLTXCachedTextEncode": LocalLTXCachedTextEncode}
NODE_DISPLAY_NAME_MAPPINGS = {"LocalLTXCachedTextEncode": "LTX Prompt Encode (Local Disk Cache)"}
