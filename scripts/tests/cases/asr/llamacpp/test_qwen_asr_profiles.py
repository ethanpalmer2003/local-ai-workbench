"""Qwen ASR selection, supervision and API transcript contracts."""

import base64
import json
import unittest
from email.message import Message
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr import selector as transcription
from scripts.launchers.asr.llamacpp import gemma_audio, llama_audio
from scripts.launchers.asr.llamacpp import qwen3_asr as qwen_asr
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.tests.shared.http_fixtures import json_response


class QwenAsrProfiles(unittest.TestCase):
    def test_alternative_selects_separate_model_projector_and_disables_embedded_whisper(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.QWEN3_ASR):
            self.assertTrue(transcription.external(cfg.KOBOLDCPP_SERVICE.transcription_engine))
            self.assertIs(transcription.backend(cfg.KOBOLDCPP_SERVICE.transcription_engine), qwen_asr)
            native = kobold.server_command()
        self.assertNotIn("--whispermodel", native)
        command = qwen_asr.command()
        for flag, value in (
            ("-m", cfg.QWEN3_ASR.model),
            ("--mmproj", cfg.QWEN3_ASR.mmproj),
            ("--port", cfg.QWEN3_ASR.port),
            ("--device", "Vulkan0"),
            ("-np", 1),
        ):
            self.assertEqual(command[command.index(flag) + 1], str(value))
        self.assertEqual(command[command.index("-fa") + 1], "on")
        self.assertNotEqual(cfg.QWEN3_ASR.port, cfg.KOBOLDCPP_KCPPS_ARGS["port"])

    def test_audio_backends_share_one_start_contract(self):
        for backend in (gemma_audio.BACKEND, qwen_asr.BACKEND):
            self.assertIsInstance(backend, llama_audio.LlamaAudioBackend)
        self.assertEqual((gemma_audio.BACKEND.alias, gemma_audio.BACKEND.label), ("gemma-audio", "Gemma audio"))
        self.assertEqual((qwen_asr.BACKEND.alias, qwen_asr.BACKEND.label), ("qwen3-asr", "Qwen ASR"))
        self.assertEqual(gemma_audio.command()[gemma_audio.command().index("--alias") + 1], "gemma-audio")
        self.assertEqual(qwen_asr.command()[qwen_asr.command().index("--alias") + 1], "qwen3-asr")

    def test_running_chat_session_preserved_and_matching_asr_reused(self):
        with (
            patch.object(llama_audio.launch_util, "llama_server_running", return_value=True),
            patch.object(qwen_asr.BACKEND, "ready", return_value=True),
            patch.object(qwen_asr.BACKEND, "matching_server", return_value=True),
            patch.object(llama_audio.launch_util, "launch_process") as launch,
        ):
            self.assertIsNone(qwen_asr.start())
        launch.assert_not_called()

    def test_transcription_text_strips_only_qwen_control_prefix(self):
        self.assertEqual(qwen_asr.clean_transcript("language English<asr_text>Hello."), "Hello.")
        self.assertEqual(qwen_asr.clean_transcript(" language French<asr_text>Un cafÃ©."), "Un cafÃ©.")
        self.assertEqual(qwen_asr.clean_transcript("<asr_text>Hello."), "Hello.")
        self.assertEqual(qwen_asr.clean_transcript("Language matters to me."), "Language matters to me.")

    def test_browser_json_converted_and_upstream_metadata_preserved(self):
        payload = {"audio_data": base64.b64encode(b"WAVE").decode(), "langcode": "fr", "prompt": "cafÃ©"}
        opened = json_response({"text": "language French<asr_text>Un cafÃ©.", "language": "fr"})
        with patch.object(qwen_asr.requests.urllib.request, "urlopen", return_value=opened) as fetch:
            body, content_type = qwen_asr.transcribe(json.dumps(payload).encode(), "application/json")
        self.assertEqual(json.loads(body), {"text": "Un cafÃ©.", "language": "fr"})
        self.assertEqual(content_type, "application/json")
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, qwen_asr.url() + "/v1/audio/transcriptions")
        self.assertIn(b'name="language"\r\n\r\nfr', request.data)
        self.assertIn("cafÃ©".encode(), request.data)

    def test_whisper_only_option_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "Whisper-specific"):
            qwen_asr.transcribe(
                json.dumps({"audio_data": base64.b64encode(b"WAVE").decode(), "suppress_non_speech": True}).encode(),
                "application/json",
            )

    def test_lite_uses_qwen_transcription_instead_of_chat_or_whisper_relay(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path, instance.headers = "/api/extra/transcribe", Message()
            instance.headers["Content-Type"] = "application/json"
            instance._forward("POST")

        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.QWEN3_ASR),
            patch.object(kobold_lite, "serve_proxy", side_effect=serve),
            patch.object(kobold_lite, "read_request_body", return_value=b"request"),
            patch.object(qwen_asr, "transcribe", return_value=(b'{"text":"Hello"}', "application/json")) as asr,
            patch.object(kobold_lite.http_api, "send_bytes") as send,
            patch.object(kobold_lite, "relay_stream") as relay,
        ):
            kobold_lite.run_proxy()
        self.assertEqual(asr.call_args.args[:2], (b"request", "application/json"))
        self.assertEqual(send.call_args.args[1:], (200, b'{"text":"Hello"}', "application/json"))
        relay.assert_not_called()
