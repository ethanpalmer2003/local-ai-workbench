"""Brief release checks use isolated native configs and model-specific controls."""

import json
import unittest
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog, audiocpp_proxy, tts_proxy
from scripts.tests.cases.audiocpp import audiocpp_backend_compare as compare
from scripts.tests.shared.paths import CasePaths


class TtsProfiles(unittest.TestCase):
    def test_ming_is_installed_for_the_page(self):
        model = cfg.AudiocppModel.MING3_TTS.value
        rows = [row for row in audiocpp_catalog.configured_models() if row["id"] == model]
        if not any(row["installed"] for row in rows):
            self.skipTest("Ming TTS weights are not installed in this checkout")
        self.assertTrue(rows)

    def test_ming_preserves_its_request(self):
        model = cfg.AudiocppModel.MING3_TTS.value
        defaults = audiocpp_catalog.runtime_defaults(cfg.AUDIOCPP_SERVICE, model)
        self.assertEqual(defaults["instruction_option"], "instruct")
        streaming = defaults["streaming"]
        assert isinstance(streaming, dict)
        self.assertEqual(streaming["pcm_sample_rate"], 44100)
        with patch.object(audiocpp_catalog, "resolve_voice_ref", return_value=("voice.wav", "Hello")):
            payload = audiocpp_proxy._transform({"model": model, "input": "Good morning.", "stream": False})
        assert payload is not None
        self.assertEqual(payload["model"], model)
        options = payload["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["seed"], 1895)
        self.assertNotIn("instruction", options)

    def test_ming_stream_log_uses_44100_hz(self):
        stats = {"audio_bytes": 88200, "ttfb": 0.2, "total": 2, "disconnected": 0}
        with patch("builtins.print") as output:
            tts_proxy._log_stream_stats("test", "1", stats, cfg.AudiocppModel.MING3_TTS.value)
        self.assertIn("dur=1s", output.call_args.args[0])

    def test_page_assets_are_explicit_and_preserve_file_opening_support(self):
        for path in ("/test/", "/test/comparison.js", "/launchers/audiocpp/pcm_audio.js", "/launchers/shared/browser/pcm_audio.js", "/launchers/shared/browser/speech_tools.js"):
            self.assertIsNotNone(tts_proxy._test_asset(path))
        self.assertIsNone(tts_proxy._test_asset("/test/../../../.env"))

    def test_release_executables_use_parallel_short_roots(self):
        self.assertEqual(compare.BUILDS["vulkan"].parent, project_cfg.AUDIOCPP_FRAMEWORK_DIR / "vulkan")
        self.assertEqual(compare.BUILDS["rocm-release"].parent, project_cfg.AUDIOCPP_FRAMEWORK_DIR / "rocm")

    def test_breeze_and_ming_generate_single_model_configs(self):
        with CasePaths(__file__).temporary_directory() as directory:
            from pathlib import Path

            for name, profile in compare.PROFILES.items():
                for backend in ("vulkan", "hip"):
                    path = Path(directory) / f"{name}-{backend}.json"
                    compare.make_config(backend, path, profile)
                    config = json.loads(path.read_text())
                    self.assertEqual(config["backend"], backend)
                    self.assertEqual(len(config["models"]), 1)
                    model = config["models"][0]
                    self.assertEqual(
                        (model["family"], model["task"], model["mode"]), (profile.family, "tts", "offline")
                    )
                    self.assertEqual(model["path"], str(profile.model))

    def test_ming_uses_its_own_seed_language_and_voice_template(self):
        profile = compare.PROFILES["ming3-tts"]
        self.assertEqual(profile.seed, 1895)
        self.assertEqual(profile.options, {"language": "en", "template_name": "ip", "voice_id": "US_James"})
        heavy = compare.PROFILES["ming3-audio"]
        self.assertEqual((heavy.family, heavy.seed), ("ming3_audio", 42))
        self.assertEqual(heavy.options, {"language": "en", "voice_id": "US_James"})

    def test_heavier_ming_is_offline_and_rejects_explicit_streaming(self):
        model = cfg.AudiocppModel.MING3_AUDIO.value
        defaults = audiocpp_catalog.runtime_defaults(cfg.AUDIOCPP_SERVICE, model)
        self.assertFalse(defaults["streaming_supported"])
        self.assertFalse(defaults["streaming_enabled"])
        self.assertIsNone(defaults["instruction_option"])
        payload: dict[str, object] = {"model": model, "input": "Good morning."}
        audiocpp_proxy._apply_stream_defaults(payload)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["response_format"], "wav")
        with self.assertRaisesRegex(ValueError, "Complete WAV"):
            audiocpp_proxy._apply_stream_defaults({"model": model, "stream": True})
        with self.assertRaisesRegex(ValueError, "Complete WAV"):
            audiocpp_proxy._apply_stream_defaults({"model": model, "stream_format": "sse"})


if __name__ == "__main__":
    unittest.main()
