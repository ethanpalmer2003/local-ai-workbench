"""HTTP proxy behavior for the launcher stack, split from the framework smoke suite."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import threading
import time
import unittest
import wave
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import requests

from scripts.config import project_config as project_cfg
from scripts.config.audiocpp import server as audio_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers import proxy_util
from scripts.launchers.audiocpp import audiocpp, audiocpp_catalog, audiocpp_proxy, tts_proxy, tts_text_processing
from scripts.launchers.sdcpp import proxy as sdcpp_proxy
from scripts.launchers.sdcpp import server as sdcpp
from scripts.shared.http_server import request, server
from scripts.tests.shared.media_fixtures import PNG, wav_fixture
from scripts.tests.shared.paths import CasePaths


class ProxyHTTP(unittest.TestCase):
    def test_model_default_refresh_passes_selected_model_to_catalog(self):
        snapshot = {
            "selected_model": cfg.AudiocppModel.FISH_DRAMA3_Q2.value,
            "packaged_defaults": {"request": {"temperature": 0.8}},
        }
        with patch.object(audiocpp_catalog, "runtime_defaults", return_value=snapshot) as defaults:
            status, body, _ = request(self.audio_url + f"/proxy/config?model={cfg.AudiocppModel.FISH_DRAMA3_Q2.value}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), snapshot)
        defaults.assert_called_once_with(cfg.AUDIOCPP_SERVICE, cfg.AudiocppModel.FISH_DRAMA3_Q2.value)

    def test_comparison_catalog_is_served_locally(self):
        catalog = {"voices": [{"id": "voice-a", "available": True}], "models": []}
        with patch.object(audiocpp_catalog, "comparison_catalog", return_value=catalog):
            status, body, _ = request(self.audio_url + "/proxy/comparison-catalog")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), catalog)
        self.assertEqual(self.requests, [])

    def test_invalid_comparison_returns_400_without_generating_a_default(self):
        with patch.object(audiocpp_catalog, "configured_models", return_value=[]):
            status, body, _ = request(
                self.audio_url + "/v1/audio/speech",
                {"input": "test", "model": "missing", "voice": "voice-a", "_comparison": True, "stream": False},
            )
        self.assertEqual(status, 400)
        self.assertIn("no fallback was used", body.decode())
        self.assertEqual(self.requests, [])

    def test_comparison_generates_wav_with_exact_voice_and_model(self):
        with (
            patch.object(cfg, "AUDIOCPP_PROXY_CLONE_VOICES", ("voice-a",)),
            patch.object(
                audiocpp_catalog,
                "configured_models",
                return_value=[{"id": cfg.AudiocppModel.BREEZE_TTS.value, "installed": True, "clone": True}],
            ),
            patch.object(audiocpp_catalog, "resolve_voice_ref", return_value=("voice-a.wav", "reference")),
        ):
            status, body, _ = request(
                self.audio_url + "/v1/audio/speech",
                {
                    "input": "Hello",
                    "model": cfg.AudiocppModel.BREEZE_TTS.value,
                    "voice": "voice-a",
                    "_comparison": True,
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"RIFF"))
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.AudiocppModel.BREEZE_TTS.value)
        self.assertEqual(forwarded["voice"], "voice-a")
        self.assertEqual(forwarded["voice_ref"], "voice-a.wav")
        self.assertNotIn("_comparison", forwarded)

    def test_test_page_reads_current_proxy_defaults(self):
        # - this route once walked the voice tree per voice and took 5.5 s; a generous bound still
        #   catches that returning, without making the check a stopwatch
        started = time.perf_counter()
        status, body, _ = request(self.audio_url + "/proxy/config")
        self.assertLess(time.perf_counter() - started, 2.0, "/proxy/config answered slower than 2 s")
        data = json.loads(body)
        self.assertEqual(status, 200)
        preset = cfg.AUDIOCPP_PROXY_MODEL_PRESETS.get(cfg.AudiocppModel(cfg.AUDIOCPP_SERVICE.model))
        expected_buffer = (
            preset.playback_buffer_ms
            if preset and preset.playback_buffer_ms is not None
            else cfg.AUDIOCPP_SERVICE.streaming.playback_buffer_ms
        )
        self.assertEqual(data["streaming"]["playback_buffer_ms"], expected_buffer)
        self.assertEqual(data["playback_note"], preset.playback_note if preset else "")
        self.assertEqual(data["streaming"]["pcm_sample_rate"], cfg.AUDIOCPP_SERVICE.streaming.pcm_sample_rate)
        self.assertEqual(data["model"], cfg.AUDIOCPP_SERVICE.model)

    def __init__(self, methodName: str = "runTest"):
        super().__init__(methodName)
        self.stack = contextlib.ExitStack()
        self.requests: list[dict[str, object]] = []
        self.image_dir = Path()
        self.sd_url = ""
        self.audio_url = ""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", False))
        self.requests = []
        calls = self.requests

        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                proxy_util.send_bytes(self, 200, b'{"status":"ok"}', "application/json")

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                calls.append(payload)
                if self.path == "/fail":
                    proxy_util.send_bytes(self, 422, b'{"error":"fixture failure"}', "application/json")
                elif self.path == "/v1/audio/speech":
                    proxy_util.send_bytes(self, 200, wav_fixture(), "audio/wav")
                else:
                    image = {"data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}
                    proxy_util.send_bytes(self, 200, json.dumps(image).encode(), "application/json")

            def log_message(self, format: str, *args: object):
                pass

        upstream = self.stack.enter_context(server(Backend))
        folder = self.stack.enter_context(CasePaths(__file__).temporary_directory())
        self.image_dir = Path(folder) / "images"
        self.stack.enter_context(patch.object(cfg, "SDCPP_OUTPUT_DIR", str(self.image_dir)))
        self.stack.enter_context(patch.object(tts_text_processing, "tone_state", tts_text_processing.ToneState()))
        with patch.object(proxy_util, "serve_proxy", autospec=True) as serve:
            proxy_util.run_json_proxy(
                cfg.SDCPP_SERVICE, upstream, transform=sdcpp_proxy._transform, on_response=sdcpp.save_generated_images
            )
        self.sd_url = self.stack.enter_context(server(serve.call_args.args[0]))
        with patch.object(tts_proxy, "serve_proxy", autospec=True) as serve:
            tts_proxy.run_tts_json_proxy(cfg.AUDIOCPP_SERVICE, upstream, transform=audiocpp_proxy._transform)
        self.audio_url = self.stack.enter_context(server(serve.call_args.args[0]))

    def test_image_generation_forwarding_and_saving(self):
        status, body, _ = request(
            self.sd_url + "/v1/images/generations",
            {"prompt": "a red cube", "model": "unknown", "steps": 1, "width": 256},
        )
        self.assertEqual(status, 200)
        self.assertIn("data", json.loads(body))
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.SDCPP_SERVICE.model)
        self.assertEqual(forwarded["steps"], 1)
        self.assertEqual(forwarded["width"], 256)
        self.assertEqual(forwarded["size"], f"256x{cfg.SDCPP_REQUEST_DEFAULTS['height']}")
        native = json.loads(str(forwarded["prompt"]).split("<sd_cpp_extra_args>")[1].split("</sd_cpp_extra_args>")[0])
        self.assertEqual(native["sample_params"]["sample_steps"], 1)
        self.assertEqual(native["negative_prompt"], cfg.SDCPP_REQUEST_DEFAULTS["negative_prompt"])
        self.assertIn("a red cube", str(forwarded["prompt"]))
        self.assertEqual(forwarded["negative_prompt"], cfg.SDCPP_REQUEST_DEFAULTS["negative_prompt"])
        files = list(self.image_dir.glob("*.png"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), PNG)

    def test_image_preload_is_not_saved_or_forwarded(self):
        self.assertEqual(
            request(self.sd_url + "/v1/images/generations", {"prompt": "cube", "_skip_save": True})[0], 200
        )
        self.assertNotIn("_skip_save", self.requests[-1])
        self.assertFalse(self.image_dir.exists())

    def test_image_invalid_json_returns_400(self):
        self.assertEqual(request(self.sd_url + "/v1/images/generations", b"{bad json")[0], 400)
        self.assertFalse(self.requests)

    def test_upstream_error_is_preserved(self):
        status, body, _ = request(self.sd_url + "/fail", {"prompt": "cube"})
        self.assertEqual(status, 422)
        self.assertIn("fixture failure", json.loads(body)["error"])

    def test_audio_default_voice_and_wav(self):
        status, body, content_type = request(
            self.audio_url + "/v1/audio/speech",
            {"input": "This is a short test.", "voice": "unknown", "model": "unknown"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "audio/wav")
        with wave.open(io.BytesIO(body), "rb") as wav:
            self.assertGreater(wav.getnframes(), 0)
            self.assertEqual(wav.getframerate(), 16000)
        forwarded = self.requests[-1]
        self.assertEqual(forwarded["model"], cfg.AUDIOCPP_SERVICE.model)
        # - an unknown clone id falls back to the configured default, which may be empty
        self.assertEqual(forwarded["voice"], cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value)
        self.assertEqual(
            "voice_ref" in forwarded, bool(audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value))
        )

    def test_audio_unicode_input_survives_logging_and_forwarding(self):
        text = "Hello, \u4e16\u754c."
        status, _, _ = request(self.audio_url + "/v1/audio/speech", {"input": text})
        self.assertEqual(status, 200)
        self.assertIn("\u4e16\u754c", str(self.requests[-1]["input"]))

    def test_audio_invalid_and_skipped_requests_do_not_stall_next_request(self):
        with patch.object(tts_proxy, "read_request_body", side_effect=ValueError("invalid Content-Length")):
            self.assertEqual(request(self.audio_url + "/v1/audio/speech", {"input": "bad read"})[0], 500)
        self.assertEqual(request(self.audio_url + "/v1/audio/speech", b"{bad json")[0], 400)
        self.assertEqual(request(self.audio_url + "/v1/audio/speech", {"input": ""})[0], 204)
        self.assertEqual(
            request(self.audio_url + "/v1/audio/speech", {"input": "This request should succeed."})[0], 200
        )

    def test_health_get_passes_through_both_proxies(self):
        for url in (self.sd_url, self.audio_url):
            with self.subTest(proxy=url):
                self.assertEqual(request(url + "/health")[0], 200)

    def test_complete_wav_preserves_upstream_audio_bytes(self):
        status, body, content_type = request(
            self.audio_url + "/v1/audio/speech", {"input": "Hello", "stream": False, "response_format": "wav"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "audio/wav")
        self.assertEqual(body, wav_fixture())

    def test_audio_stream_arrives_before_generation_finishes(self):
        finish = threading.Event()

        class StreamingBackend(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "audio/pcm")
                self.end_headers()
                self.wfile.write(b"first")
                self.wfile.flush()
                finish.wait(3)
                self.wfile.write(b"last")

            def log_message(self, format: str, *args: object):
                pass

        with server(StreamingBackend) as upstream:
            with patch.object(tts_proxy, "serve_proxy") as serve:
                tts_proxy.run_tts_json_proxy(cfg.AUDIOCPP_SERVICE, upstream, transform=audiocpp_proxy._transform)
            with server(serve.call_args.args[0]) as proxy:
                body = json.dumps({"input": "Hello", "stream": True}).encode()
                try:
                    with requests.post(proxy + "/v1/audio/speech", data=body, timeout=2, stream=True) as response:
                        response.raise_for_status()
                        self.assertEqual(response.raw.read1(5), b"first")
                        self.assertFalse(finish.is_set())
                        finish.set()
                        self.assertEqual(response.raw.read(), b"last")
                finally:
                    finish.set()

    def test_streaming_transform_sets_native_response_format(self):
        with patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True):
            result = audiocpp_proxy._transform({"input": "Hello"})
        self.assertIsNotNone(result)
        assert result is not None
        payload = result
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["response_format"], "pcm")
        options = payload["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["text_chunk_mode"], "tag_aware")

        self.assertEqual(
            "voice_ref" in payload, bool(audiocpp_catalog.resolve_voice_ref(cfg.DEFAULT_AUDIOCPP_PROXY_VOICE.value))
        )

    def test_vocal_event_toggle_is_independent_of_tones_and_audio_streaming(self):
        for streaming in (False, True):
            for enabled in (False, True):
                settings = replace(tts_text_processing.BREEZE_VOCAL_EVENTS, enabled=enabled)
                tones = replace(tts_text_processing.BREEZE_TONES, tags_enabled=False, default_instruction="")
                with (
                    self.subTest(streaming=streaming, enabled=enabled),
                    patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings),
                    patch.object(tts_text_processing, "BREEZE_TONES", tones),
                ):
                    result = audiocpp_proxy._transform(
                        {"input": "(giggle softly) Hello. (waves hello)", "stream": streaming}
                    )
                    assert result is not None
                    expected = "(giggle) Hello. waves hello" if enabled else "(giggle softly) Hello. (waves hello)"
                    self.assertEqual(result["input"], expected)

    def test_vocal_parenthetical_modes_preserve_known_events(self):
        for mode, expected in (
            (tts_text_processing.BreezeParenMode.KEEP, "(laugh) (giggle) (waves hello)"),
            (tts_text_processing.BreezeParenMode.UNWRAP, "(laugh) (giggle) waves hello"),
            (tts_text_processing.BreezeParenMode.STRIP, "(laugh) (giggle) "),
        ):
            settings = replace(tts_text_processing.BREEZE_VOCAL_EVENTS, parentheticals=mode)
            with patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings):
                self.assertEqual(
                    tts_text_processing.filter_breeze_vocal_events("(laugh) (giggles) (waves hello)"), expected
                )
        settings = replace(
            tts_text_processing.BREEZE_VOCAL_EVENTS, parentheticals=tts_text_processing.BreezeParenMode.STRIP
        )
        with patch.object(tts_text_processing, "BREEZE_VOCAL_EVENTS", settings):
            self.assertIsNone(
                tts_text_processing.clean_text({"input": "(waves hello)", "model": cfg.AudiocppModel.BREEZE_TTS.value})[
                    0
                ]
            )

    def test_other_models_do_not_receive_breeze_text_rules(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                result = audiocpp_proxy._transform(
                    {
                        "input": '[Tone: happy] "Hello." (giggle softly)',
                        "model": cfg.AudiocppModel.FISH_DRAMA3_Q2.value,
                        "stream": streaming,
                        "_tone_tag": "sad",
                    }
                )
                assert result is not None
                payload = result
                self.assertEqual(payload["input"], '[Tone: happy] "Hello." (giggle softly)')
                self.assertNotIn("_tone_tag", payload)
                options = payload.get("options", {})
                assert isinstance(options, dict)
                self.assertNotIn("instruction", options)

    def test_streaming_tones_extract_inherit_and_preserve_explicit_options(self):
        with patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True):
            for text, options, expected in (
                ("[Tone: cheerful] Hello!", {}, "cheerful"),
                ("Still happy.", {}, "cheerful"),
                ("[Tone: sad] Goodbye.", {"instruction": "whisper", "guidance_scale": 2}, "whisper"),
                ("Quiet now.", {}, "whisper"),
            ):
                result = audiocpp_proxy._transform({"input": text, "options": options})
                assert result is not None
                payload = result
                spoken = payload["input"]
                request_options = payload["options"]
                assert isinstance(spoken, str) and isinstance(request_options, dict)
                self.assertNotIn("[Tone:", spoken)
                self.assertEqual(request_options["instruction"], expected)

                if "guidance_scale" in options:
                    self.assertEqual(request_options["guidance_scale"], 2)

    def test_tone_switch_combinations_use_last_before_default(self):
        for tags in (True, False):
            for default in (True, False):
                settings = replace(
                    tts_text_processing.BREEZE_TONES, tags_enabled=tags, default_instruction="calm" if default else ""
                )
                with (
                    self.subTest(tags=tags, default=default),
                    patch.object(tts_text_processing, "BREEZE_TONES", settings),
                    patch.object(tts_text_processing, "tone_state", tts_text_processing.ToneState()),
                ):
                    fallback = "calm" if default else ""
                    for text, expected in (
                        ("Hello.", fallback),
                        ("[Tone: happy] Hi!", "happy" if tags else fallback),
                        ("Again.", "happy" if tags else fallback),
                    ):
                        payload: dict[str, object] = {"input": text}
                        tts_text_processing.apply_breeze_tone(payload)
                        options = payload["options"]
                        spoken = payload["input"]
                        assert isinstance(options, dict) and isinstance(spoken, str)
                        self.assertEqual(options["instruction"], expected)
                        self.assertNotIn("[Tone:", spoken)
                    payload = {
                        "input": "Hello.",
                        "_tone_tag": "sad",
                        "options": {"instruction": "whisper", "guidance_scale": 3},
                    }
                    tts_text_processing.apply_breeze_tone(payload)
                    self.assertEqual(payload["options"], {"instruction": "whisper", "guidance_scale": 3})
                    self.assertNotIn("_tone_tag", payload)

    def test_forwarded_tone_is_ignored_when_tags_disabled(self):
        settings = replace(tts_text_processing.BREEZE_TONES, tags_enabled=False, default_instruction="calm")
        with patch.object(tts_text_processing, "BREEZE_TONES", settings):
            tts_text_processing.tone_state.last = "old tone"
            payload: dict[str, object] = {"input": "Hello.", "_tone_tag": "happy"}
            tts_text_processing.apply_breeze_tone(payload)
            options = payload["options"]
            assert isinstance(options, dict)
            self.assertEqual(options["instruction"], "calm")
            self.assertIsNone(tts_text_processing.tone_state.last)

    def test_streaming_launch_reads_native_config_without_generating_a_copy(self):
        source = Path(cfg.AUDIOCPP_SERVER_ARGS["config"])
        original = json.dumps(audio_cfg.read(source)).encode("utf-8")
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "GENERATED_DIR", Path(folder)),
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
            patch.object(audiocpp, "launch_process") as launch,
            patch.object(audiocpp, "print_ready"),
        ):
            audiocpp.launch(report_vram=False)
            command = launch.call_args.args[0]
            runtime_path = Path(command[command.index("--config") + 1])
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            expected = json.loads(original)
            self.assertEqual(runtime, expected)
            self.assertEqual(runtime_path, Path(folder) / "shared" / "configs" / source.name)
            self.assertNotIn("{AI_ROOT}", runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(audio_cfg.read(source), json.loads(original))

    def test_streaming_defaults_preserve_explicit_request_options(self):
        settings = replace(cfg.AUDIOCPP_SERVICE.streaming, stream_frames_per_event=16, stream_lookahead_margin=12)
        with (
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming", settings),
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
        ):
            result = audiocpp_proxy._transform({"input": "Hello", "options": {"stream_frames_per_event": 8}})
        assert result is not None
        options = result["options"]
        assert isinstance(options, dict)
        self.assertEqual(options["stream_frames_per_event"], 8)
        self.assertEqual(options["stream_lookahead_margin"], 12)

    def test_explicit_buffered_request_overrides_streaming_default(self):
        with (
            patch.object(cfg.AUDIOCPP_SERVICE, "streaming_enabled", True),
            patch.object(tts_text_processing, "clean_text", return_value=("Hello", 0.0)),
        ):
            result = audiocpp_proxy._transform({"input": "Hello", "stream": False, "response_format": "wav"})
        assert result is not None
        payload = result
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["response_format"], "wav")
        self.assertNotIn("stream_format", payload)
