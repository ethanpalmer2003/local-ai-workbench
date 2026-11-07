"""Gemma audio boundaries and transcript contracts, without loading model weights."""

import base64
import io
import json
import unittest
from unittest.mock import patch

from scripts.launchers.asr.llamacpp import gemma_audio
from scripts.tests.shared.media_fixtures import pcm_wav as wav


class GemmaAudioTests(unittest.TestCase):
    def test_empty_and_over_limit_are_rejected_without_truncation(self):
        for audio in (wav(0), wav(480001)):
            with self.subTest(bytes=len(audio)), self.assertRaisesRegex(ValueError, "up to 30"):
                gemma_audio.prepare_audio(audio)

    def test_exact_limit_is_accepted(self):
        encoded, duration = gemma_audio.prepare_audio(wav(480000))
        self.assertEqual(duration, 30)
        self.assertTrue(base64.b64decode(encoded).startswith(b"RIFF"))

    def test_stereo_and_resampling_produce_mono_16k(self):
        import wave

        encoded, duration = gemma_audio.prepare_audio(wav(48000, 48000, 2))
        self.assertEqual(duration, 1)
        with wave.open(io.BytesIO(base64.b64decode(encoded))) as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (1, 16000, 16000))

    def test_undecodable_input_is_a_request_error(self):
        with self.assertRaisesRegex(ValueError, "Cannot decode"):
            gemma_audio.prepare_audio(b"not audio")

    def test_response_formats_and_prompt_are_preserved(self):
        payload = {"audio_data": base64.b64encode(wav(1600)).decode(), "langcode": "fr", "prompt": "caf\u00e9"}
        for response_format in ("json", "text"):
            payload["response_format"] = response_format
            response = {"choices": [{"message": {"content": "  Un caf\u00e9.  "}, "finish_reason": "stop"}]}
            with patch.object(
                gemma_audio.requests, "post", return_value=(json.dumps(response).encode(), "application/json")
            ) as post:
                data, kind = gemma_audio.transcribe(json.dumps(payload).encode(), "application/json")
            sent = json.loads(post.call_args.args[1])
            prompt = sent["messages"][0]["content"][0]["text"]
            self.assertIn("French", prompt)
            self.assertIn("caf\u00e9", prompt)
            self.assertEqual(json.loads(data)["text"] if response_format == "json" else data.decode(), "Un caf\u00e9.")
            self.assertIn("json" if response_format == "json" else "text/plain", kind)

    def test_invalid_empty_and_truncated_transcripts_fail(self):
        payload = json.dumps({"audio_data": base64.b64encode(wav(1600)).decode()}).encode()
        responses = (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": " "}}]},
            {"choices": [{"message": {"content": "Partial"}, "finish_reason": "length"}]},
        )
        for value in responses:
            with (
                self.subTest(value=value),
                patch.object(
                    gemma_audio.requests, "post", return_value=(json.dumps(value).encode(), "application/json")
                ),
                self.assertRaises(RuntimeError),
            ):
                gemma_audio.transcribe(payload, "application/json")


if __name__ == "__main__":
    unittest.main()
