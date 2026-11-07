"""CPU-only tests for lazy prompt caching and invalidation.

The node itself runs inside ComfyUI's interpreter, which owns torch; tests that need
tensors skip when this venv has no torch, and the cache-key tests always run.
"""

import importlib.util
import math
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from scripts.config.comfyui import ltx_prompt_cache
from scripts.tests.shared.paths import CasePaths

HAS_TORCH = importlib.util.find_spec("torch") is not None


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
        self.modules = patch.dict("sys.modules", {"folder_paths": self.folder_paths})
        self.cache = patch.object(ltx_prompt_cache, "CACHE_DIR", self.paths.temp / "cache")

    def setUp(self) -> None:
        self.modules.start()
        self.cache.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.cache.stop)

    @unittest.skipUnless(HAS_TORCH, "torch belongs to the ComfyUI interpreter")
    def test_hit_skips_encoder_and_preserves_conditioning(self) -> None:
        import torch

        node = ltx_prompt_cache.LocalLTXCachedTextEncode()
        clip = MagicMock()
        clip.encode_from_tokens_scheduled.return_value = [
            [torch.ones(2, 3), {"pooled_output": torch.zeros(1, 3), "tag": "test"}]
        ]
        self.assertEqual(node.check_lazy_status(None, "red car", True, self.prompt, "6"), ["clip"])
        original = node.encode(clip, "red car", True, self.prompt, "6")[0]
        self.assertEqual(node.check_lazy_status(None, "red car", True, self.prompt, "6"), [])
        cached = node.encode(None, "red car", True, self.prompt, "6")[0]
        self.assertTrue(torch.equal(original[0][0], cached[0][0]))
        self.assertTrue(torch.equal(original[0][1]["pooled_output"], cached[0][1]["pooled_output"]))
        self.assertEqual(cached[0][1]["tag"], "test")
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
