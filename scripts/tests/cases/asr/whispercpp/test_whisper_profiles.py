"""External Whisper routing, startup safety and native request compatibility."""

import base64
import io
import json
import unittest
from email import policy
from email.message import Message
from email.parser import BytesParser
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.asr.whispercpp import server as whisper
from scripts.launchers.koboldcpp import kobold, kobold_lite
from scripts.tests.shared.http_fixtures import json_response


class WhisperProfiles(unittest.TestCase):
    def test_external_cli_refuses_an_existing_kobold_session_before_starting_whisper(self):
        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.EMBEDDED),
            patch.object(kobold, "backend_running", return_value=False),
            patch.object(kobold, "port_listening", return_value=True),
            patch.object(whisper, "start") as start,
            self.assertRaisesRegex(RuntimeError, "occupied"),
        ):
            kobold.main(["--transcription-engine", "whisper-vulkan"])
        start.assert_not_called()

    def test_external_profile_omits_embedded_model_and_selects_current_vulkan_flash(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.WHISPER_VULKAN):
            native = kobold.server_command()
        self.assertNotIn("--whispermodel", native)
        standalone = whisper.command()
        self.assertEqual(standalone[0], str(cfg.WHISPERCPP_ASR.exe))
        self.assertEqual(standalone[standalone.index("-m") + 1], str(cfg.WHISPERCPP_ASR.model))
        self.assertIn("-fa", standalone)
        self.assertNotIn("-nfa", standalone)
        self.assertNotIn("-ng", standalone)

    def test_browser_audio_language_prompt_and_suppression_survive_conversion(self):
        audio = b"RIFF\x00\x01\xffWAVE"
        request = {
            "audio_data": "data:audio/wav;base64," + base64.b64encode(audio).decode(),
            "langcode": " FR ",
            "prompt": "un cafÃ©",
            "suppress_non_speech": True,
        }
        body, content_type = whisper.transcription_body(json.dumps(request).encode(), "application/json")
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        values = {
            part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
            for part in message.iter_parts()
        }
        self.assertEqual(values["file"], audio)
        self.assertEqual(values["language"], b"fr")
        self.assertEqual(values["prompt"], "un cafÃ©".encode())
        self.assertEqual(values["suppress_non_speech"], b"true")
        self.assertEqual(values["response_format"], b"json")

    def test_invalid_audio_is_rejected_and_openai_multipart_is_preserved(self):
        for payload in ([], {}, {"audio_data": "!bad!"}, {"audio_data": "data:audio/wav;base64,"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                whisper.transcription_body(json.dumps(payload).encode(), "application/json")
        self.assertEqual(
            whisper.transcription_body(b"upload", "multipart/form-data; boundary=abc"),
            (b"upload", "multipart/form-data; boundary=abc"),
        )

    def test_lite_transcription_uses_external_endpoint_and_replaces_content_type(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path = "/api/extra/transcribe"
            instance.headers = Message()
            instance.headers["content-type"] = "application/json"
            instance.headers["Authorization"] = "Bearer local-test"
            instance._forward("POST")

        payload = json.dumps({"audio_data": base64.b64encode(b"WAVE").decode(), "langcode": "en"}).encode()
        opened = json_response({"text": "Hello"})
        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.WHISPER_VULKAN),
            patch.object(kobold_lite, "serve_proxy", side_effect=serve),
            patch.object(kobold_lite, "read_request_body", return_value=payload),
            patch.object(whisper.requests.urllib.request, "urlopen", return_value=opened) as fetch,
            patch.object(kobold_lite.http_api, "send_bytes"),
        ):
            kobold_lite.run_proxy()
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, whisper.url() + "/inference")
        self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data; boundary="))
        self.assertEqual(request.get_header("Authorization"), "Bearer local-test")

    def test_lite_advertises_external_transcription_only_when_ready(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path, instance.headers = "/api/extra/version", Message()
            instance._forward("GET")

        for ready in (True, False):
            with (
                self.subTest(ready=ready),
                patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.WHISPER_VULKAN),
                patch.object(kobold_lite, "serve_proxy", side_effect=serve),
                patch.object(
                    kobold_lite.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(json.dumps({"transcribe": False, "llm": True, "tts": False}).encode()),
                ),
                patch.object(whisper, "ready", return_value=ready),
                patch.object(kobold_lite, "send_bytes") as send,
            ):
                kobold_lite.run_proxy()
            self.assertEqual(json.loads(send.call_args.args[2]), {"transcribe": ready, "llm": True, "tts": False})
