"""CPU-only tests for lazy prompt caching and invalidation.

The node imports torch because ComfyUI's interpreter owns it. The cache contract does
not need real tensors, so this file installs a pickle-backed stand-in and tests what
this repository decides: when the encoder is skipped, what a hit returns, and when
the key changes.
"""

import copy
import math
import pathlib
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from scripts.config.comfyui import ltx_prompt_cache
from scripts.tests.shared.paths import CasePaths


class _StandInTensor:
    """Marks the objects the fake torch reports as tensors, and answers the CPU copy the cache makes."""

    def detach(self) -> "_StandInTensor":
        return self

    def to(self, *args: object) -> "_StandInTensor":
        return self

    def contiguous(self) -> "_StandInTensor":
        return self


_STORED: dict[str, object] = {}


def fake_torch() -> ModuleType:
    """Stand in for the cache's serializer: a file marks the hit, the value stays in memory."""
    module = ModuleType("torch")
    module.Tensor = _StandInTensor

    def save(value: object, path: str) -> None:
        _STORED[str(path)] = copy.deepcopy(value)
        pathlib.Path(path).write_bytes(b"stored")

    def load(path: str, map_location: object = None, weights_only: bool = True) -> object:
        # - the cache writes to a temp name and renames it, so match on the shared stem
        key = str(path)
        stem = key.rsplit(".", 1)[0]
        for stored, value in _STORED.items():
            if stored == key or stored.startswith(stem):
                return copy.deepcopy(value)
        raise KeyError(key)

    module.save = save
    module.load = load
    return module


class PromptCacheTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.paths = CasePaths(__file__).new_run()
        self.model = self.paths.temp / "encoder.gguf"
        self.model.write_bytes(b"test encoder metadata")
        self.folder_paths = ModuleType("folder_paths")
        self.folder_paths.__file__ = str(self.paths.temp / "folder_paths.py")
        self.folder_paths.__dict__["get_full_path_or_raise"] = MagicMock(return_value=str(self.model))
        self.prompt = {
            "6": {"inputs": {"clip": ["35", 0]}},
            "35": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "encoder.gguf", "type": "ltxv"}},
        }
        self.modules = patch.dict("sys.modules", {"folder_paths": self.folder_paths, "torch": fake_torch()})
        self.cache = patch.object(ltx_prompt_cache, "CACHE_DIR", self.paths.temp / "cache")

    def setUp(self) -> None:
        self.modules.start()
        self.cache.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.cache.stop)

    def test_hit_skips_encoder_and_preserves_conditioning(self) -> None:
        node = ltx_prompt_cache.LocalLTXCachedTextEncode()
        clip = MagicMock()
        clip.encode_from_tokens_scheduled.return_value = [[_StandInTensor(), {"pooled_output": _StandInTensor()}]]
        self.assertEqual(node.check_lazy_status(None, "red car", True, self.prompt, "6"), ["clip"])
        node.encode(clip, "red car", True, self.prompt, "6")
        self.assertEqual(node.check_lazy_status(None, "red car", True, self.prompt, "6"), [])
        cached = node.encode(None, "red car", True, self.prompt, "6")[0]
        self.assertIsInstance(cached[0][0], _StandInTensor, "a hit returns the stored tensor")
        self.assertIsInstance(cached[0][1]["pooled_output"], _StandInTensor)
        clip.encode_from_tokens_scheduled.assert_called_once()

    def test_prompt_encoder_and_version_invalidate_cache(self) -> None:
        original = ltx_prompt_cache.cache_file("red car", self.prompt, "6")
        self.assertNotEqual(original, ltx_prompt_cache.cache_file("blue car", self.prompt, "6"))
        self.model.write_bytes(b"updated encoder metadata")
        updated = ltx_prompt_cache.cache_file("red car", self.prompt, "6")
        self.assertNotEqual(original, updated)
        (self.paths.temp / ".last_update_hash").write_text("new-runtime", encoding="utf-8")
        self.assertNotEqual(updated, ltx_prompt_cache.cache_file("red car", self.prompt, "6"))

    def test_disabled_cache_requests_encoder(self) -> None:
        node = ltx_prompt_cache.LocalLTXCachedTextEncode()
        self.assertEqual(node.check_lazy_status(None, "red car", False, self.prompt, "6"), ["clip"])
        changed = node.IS_CHANGED(None, "red car", False, self.prompt, "6")
        assert isinstance(changed, float)
        self.assertTrue(math.isnan(changed))


if __name__ == "__main__":
    unittest.main()
