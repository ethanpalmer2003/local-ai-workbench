"""Comparison selection safety without model inference."""

import json
import struct
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.config import models as model_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.audiocpp import audiocpp_catalog, audiocpp_proxy
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

    def test_a_named_voice_model_reports_its_own_default(self):
        for model, mode, voice, clone, instruction, guidance in (
            ("audiocpp/supertonic-3-q8_0", "builtin", "F1", False, None, None),
            ("audiocpp/kokoro-audiocpp-multilingual-q8_0", "builtin", "af_heart", False, None, None),
            ("audiocpp/ming3-tts-0.5b-q8_0", "both", "US_James", True, "instruct", "guidance_scale"),
            ("audiocpp/ming3-audio-tiny-q4_k", "clone", "persona", True, None, "guidance_scale"),
        ):
            if not model_cfg.path(model).is_file():
                continue
            data = audiocpp_catalog.runtime_defaults(cfg.AUDIOCPP_SERVICE, model)
            self.assertEqual(data["voice_mode"], mode, model)
            self.assertEqual(data["voice"], voice, model)
            self.assertEqual(audiocpp_catalog.supports_clone(model), clone, model)
            self.assertEqual(data["instruction_option"], instruction, model)
            self.assertEqual(data["guidance_scale_option"], guidance, model)

    def test_only_a_reference_model_reports_the_clone_voice(self):
        model = "audiocpp/breeze-tts-2-q4_0"
        if not model_cfg.path(model).is_file():
            self.skipTest("Breeze weights are not installed")
        data = audiocpp_catalog.runtime_defaults(cfg.AUDIOCPP_SERVICE, model)
        self.assertEqual(data["voice_mode"], "clone")
        self.assertEqual(data["voice"], cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
        self.assertEqual(data["instruction_option"], "instruction")
        self.assertEqual(data["guidance_scale_option"], "guidance_scale")

    def test_a_named_voice_model_gets_its_default_voice_id(self):
        options: dict[str, object] = {}
        payload: dict[str, object] = {"input": "hi", "options": options}
        with (
            patch.object(audiocpp_catalog, "declares_voice_presets", return_value=True),
            patch.object(audiocpp_catalog, "default_voice_for", return_value="F1"),
            patch.object(audiocpp_catalog, "server_request_defaults", return_value={}),
        ):
            audiocpp_proxy._apply_request_options(payload, None, "audiocpp/supertonic-3-q8_0")
        self.assertEqual(options["voice_id"], "F1")

    def test_a_request_option_the_model_does_not_declare_is_dropped(self):
        preset = cfg.AUDIOCPP_PROXY_MODEL_PRESETS[cfg.AudiocppModel.BREEZE_TTS]
        options: dict[str, object] = {"language": "en", "instruction": "calm", "guidance_scale": 4.0}
        payload: dict[str, object] = {"input": "hi", "options": options}
        accepted = frozenset({"guidance_scale", "instruct", "instruction"})
        with patch.object(audiocpp_catalog, "accepted_request_options", return_value=accepted):
            audiocpp_proxy._apply_request_options(payload, preset, cfg.AudiocppModel.BREEZE_TTS.value)
        self.assertNotIn("language", options)
        self.assertEqual(options["instruction"], "calm")
        self.assertEqual(options["guidance_scale"], 4.0)

    def test_the_installed_spec_accepts_the_spelling_the_tone_path_sends(self):
        accepted = audiocpp_catalog.accepted_request_options(cfg.AudiocppModel.BREEZE_TTS.value)
        self.assertIn("instruction", accepted)
        self.assertNotIn("language", accepted)

    def test_a_model_that_declares_no_request_options_keeps_the_client_keys(self):
        payload: dict[str, object] = {"input": "hi", "options": {"language": "en"}}
        with (
            patch.object(audiocpp_catalog, "accepted_request_options", return_value=frozenset()),
            patch.object(audiocpp_catalog, "server_request_defaults", return_value={}),
            patch.object(audiocpp_catalog, "declares_voice_presets", return_value=False),
        ):
            audiocpp_proxy._apply_request_options(payload, None, cfg.AudiocppModel.MING3_TTS.value)
        self.assertEqual(payload["options"], {"language": "en"})

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
                # - the fixture's placeholder files carry no model spec, so the packaging answer is supplied
                patch.object(audiocpp_catalog, "_accepts_reference", return_value=True),
                patch.object(audiocpp_catalog, "_declares_voice_presets", return_value=False),
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
