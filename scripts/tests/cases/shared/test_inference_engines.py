"""Avalon adapter contract and normalized result semantics; no model or GPU required."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.inference_engines.engines import avalon
from scripts.benchmarks.inference_engines.engines.avalon import AvalonEngine
from scripts.benchmarks.inference_engines.engines.base import RunSpec, failed, skipped


class InferenceEngines(unittest.TestCase):
    def test_avalon_serves_the_strata_weights_without_speculation(self):
        argv = avalon.command(Path("avalon.log"))
        model = Path(argv[argv.index("-m") + 1])
        self.assertEqual(model.name, "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf")
        self.assertEqual(argv[argv.index("--spec-type") + 1], "draft-mtp")
        self.assertEqual(Path(argv[argv.index("-md") + 1]).name, "mtp-Qwen3.8-Flash-Next-shared-IQ3K-IQ4NL-FR65k.gguf")
        self.assertEqual(argv[argv.index("--moe-cache") + 1], "auto")
        self.assertEqual(argv[argv.index("--cache-ram") + 1], avalon.CACHE_RAM_MIB)
        self.assertEqual(avalon.ENV["GGML_CUDA_MOE_CACHE_MIN_EXPERT_KB"], "1")

    def test_missing_avalon_install_is_skipped(self):
        with patch.object(avalon, "server_exe", return_value=Path("missing/llama-server.exe")):
            ready, reason = AvalonEngine().available(RunSpec("avalon/strata"))
        self.assertFalse(ready)
        self.assertIn("not installed", reason)

    def test_skipped_and_failed_results_are_not_measurements(self):
        spec = RunSpec("demo", model="m")
        self.assertEqual(skipped("hipfire", spec, "Linux only").status, "skipped")
        self.assertEqual(skipped("hipfire", spec, "Linux only").decode_tokens_per_second, None)
        failure = failed("llamacpp", spec, RuntimeError("boom"))
        self.assertEqual(failure.status, "failed")
        self.assertEqual(failure.reason, "boom")


if __name__ == "__main__":
    unittest.main()
