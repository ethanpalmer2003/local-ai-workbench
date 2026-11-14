"""Comparison selection safety without model inference."""

import json
import struct
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog, audiocpp_proxy
from scripts.tests.shared.model_checks import requires_model_check
from scripts.tests.shared.paths import CasePaths


class AudioComparison(unittest.TestCase):
    def test_proxy_transport_inherits_config_but_explicit_client_choice_wins(self):
        with patch.object(cfg.AUDIOCPP_SERVICE.streaming, "transport", cfg.SharedTtsStreamingRequestTransport.SSE):
            inherited: dict[str, object] = {}
            audiocpp_proxy._apply_stream_defaults(inherited)
            self.assertEqual(inherited["stream_format"], "sse")
            explicit: dict[str, object] = {"stream_format": "audio"}
            audiocpp_proxy._apply_stream_defaults(explicit)
            self.assertEqual(explicit["stream_format"], "audio")
            complete: dict[str, object] = {"stream": False}
            audiocpp_proxy._apply_stream_defaults(complete)
            self.assertNotIn("stream_format", complete)

    def test_streaming_forces_pcm_response_format_from_client_wav(self):
        for payload in ({"response_format": "wav"}, {"stream_format": "audio", "response_format": "wav"}):
            value: dict[str, object] = dict(payload)
            audiocpp_proxy._apply_stream_defaults(value)
            self.assertIs(value["stream"], True)
            self.assertEqual(value["response_format"], "pcm")

    @requires_model_check
    def test_live_defaults_read_model_metadata_and_refresh_after_file_changes(self):
        def write_model(path: Path, temperature: float):
            spec = json.dumps({"options": {"request": [{"name": "temperature", "default": temperature}]}}).encode()
            key = b"audiocpp.model_spec.json"
            path.write_bytes(
                struct.pack("<4sIQQ", b"GGUF", 3, 0, 1)
                + struct.pack("<Q", len(key))
                + key
                + struct.pack("<IQ", 8, len(spec))
                + spec
            )

        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            config = root / "server.json"
            model = root / "breeze.gguf"
            config.write_text(
                json.dumps({"models": [{"id": cfg.AudiocppModel.BREEZE_TTS.value, "path": "breeze.gguf"}]}),
                encoding="utf-8",
            )
            write_model(model, 0.9)
            with patch.dict(cfg.AUDIOCPP_SERVER_ARGS, {"config": str(config)}):
                service = replace(cfg.AUDIOCPP_SERVICE, model=cfg.AudiocppModel.BREEZE_TTS.value)
                first = audiocpp_catalog.runtime_defaults(service)
                self.assertEqual(first["packaged_defaults"], {"request": {"temperature": 0.9}})
                write_model(model, 1.25)
                refreshed = audiocpp_catalog.runtime_defaults(service)
                self.assertEqual(refreshed["packaged_defaults"], {"request": {"temperature": 1.25}})
                self.assertEqual(refreshed["streaming"], first["streaming"])
                self.assertEqual(refreshed["streaming_enabled"], cfg.AUDIOCPP_SERVICE.streaming_enabled)
                streaming = refreshed["streaming"]
                assert isinstance(streaming, dict)
                self.assertNotIn("enabled", streaming)

    def test_catalog_reports_local_files_and_excludes_non_tts_entries(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "breeze.gguf").write_bytes(b"model")
            config = root / "server.json"
            config.write_text(
                json.dumps(
                    {
                        "models": [
                            {"id": cfg.AudiocppModel.BREEZE_TTS.value, "path": "breeze.gguf"},
                            {"id": cfg.AudiocppModel.FISH_DRAMA3_Q2.value, "path": "missing.gguf"},
                            {"id": cfg.AudiocppModel.BREEZE_DESIGN.value, "path": "breeze.gguf"},
                            {"id": "asr/audiocpp/higgs-audio-v3-stt-q8_0", "path": "breeze.gguf"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ("test-voice", "other-voice")),
                patch.dict(cfg.AUDIOCPP_SERVER_ARGS, {"config": str(config)}),
                patch.object(audiocpp_catalog, "_voice_refs", return_value={"test-voice": Path("voice.wav")}),
            ):
                catalog = audiocpp_catalog.comparison_catalog()
            self.assertEqual(
                catalog["models"],
                [
                    {"id": cfg.AudiocppModel.BREEZE_TTS.value, "installed": True, "clone": True},
                    {"id": cfg.AudiocppModel.FISH_DRAMA3_Q2.value, "installed": False, "clone": True},
                    {"id": cfg.AudiocppModel.BREEZE_DESIGN.value, "installed": True, "clone": False},
                ],
            )
            self.assertIn({"id": "test-voice", "available": True}, catalog["voices"])
            self.assertIn({"id": "other-voice", "available": False}, catalog["voices"])

    def test_comparison_rejects_missing_model_or_voice_before_default_fallback(self):
        catalog = {"models": [{"id": cfg.AudiocppModel.BREEZE_TTS.value, "installed": True, "clone": True}]}
        with (
            patch.object(cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ("test-voice", "other-voice")),
            patch.object(audiocpp_catalog, "configured_models", return_value=catalog["models"]),
            patch.object(audiocpp_catalog, "resolve_voice_ref", return_value=None),
            patch.object(audiocpp_proxy, "_apply_model_fallback") as fallback,
        ):
            for model, voice in [("unknown", "test-voice"), (cfg.AudiocppModel.BREEZE_TTS.value, "test-voice")]:
                with self.assertRaisesRegex(ValueError, "no fallback was used"):
                    audiocpp_proxy._transform({"_comparison": True, "model": model, "voice": voice})
            fallback.assert_not_called()

    def test_valid_comparison_retains_exact_selection(self):
        catalog = {"models": [{"id": cfg.AudiocppModel.BREEZE_TTS.value, "installed": True, "clone": True}]}
        with (
            patch.object(cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ("test-voice", "other-voice")),
            patch.object(audiocpp_catalog, "configured_models", return_value=catalog["models"]),
            patch.object(audiocpp_catalog, "resolve_voice_ref", return_value=("test-voice.wav", "reference")),
        ):
            payload: dict[str, object] = {"model": cfg.AudiocppModel.BREEZE_TTS.value, "voice": "test-voice"}
            audiocpp_catalog.validate_comparison(payload)
            self.assertEqual(payload, {"model": cfg.AudiocppModel.BREEZE_TTS.value, "voice": "test-voice"})


if __name__ == "__main__":
    unittest.main()
