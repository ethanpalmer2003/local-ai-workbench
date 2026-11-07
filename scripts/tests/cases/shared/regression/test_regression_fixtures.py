"""Fixture contracts prevent misleading successes from permissive or inconsistent mocks."""

import io
import struct
import unittest
import wave
from subprocess import TimeoutExpired
from unittest.mock import patch

from scripts.tests.shared.http_fixtures import http_response, json_response
from scripts.tests.shared.media_fixtures import pcm_wav
from scripts.tests.shared.process_fixtures import exited_process, running_process


class RegressionFixtures(unittest.TestCase):
    def test_process_timeout_does_not_pretend_exit_and_successful_wait_does(self):
        worker = running_process(wait_timeouts=1)
        with self.assertRaises(TimeoutExpired):
            worker.wait(timeout=1)
        self.assertIsNone(worker.poll())
        self.assertEqual(worker.wait(timeout=1), 0)
        self.assertEqual(worker.poll(), 0)
        exited = exited_process(exit_code=7)
        self.assertEqual(exited.wait(timeout=1), 7)
        self.assertEqual(exited.poll(), 7)
        untimed = running_process(wait_timeouts=1)
        self.assertEqual(untimed.wait(), 0)
        self.assertEqual(untimed.poll(), 0)

    def test_process_fixture_never_calls_popen_even_when_popen_is_patched(self):
        with patch("subprocess.Popen") as launch:
            worker = running_process()
        launch.assert_not_called()
        self.assertIsNone(worker.poll())
        with self.assertRaises(AttributeError):
            worker.nonexistent_process_api()

    def test_http_context_closes_and_never_swallows_failures(self):
        response = http_response(b"\x00binary", headers={"Content-Range": "bytes 0-6/7"})
        with self.assertRaisesRegex(ValueError, "fixture failure"), response as opened:
            self.assertEqual(opened.read(), b"\x00binary")
            self.assertEqual(opened.headers.get("content-range"), "bytes 0-6/7")
            raise ValueError("fixture failure")
        response.close.assert_called_once()
        self.assertEqual(json_response({"text": "caf\u00e9"}).json(), {"text": "caf\u00e9"})

    def test_error_status_and_stream_chunks_remain_explicit(self):
        from requests import HTTPError

        response = http_response(status=503, chunks=[b"first", b"second"])
        with self.assertRaises(HTTPError) as error:
            response.raise_for_status()
        self.assertIs(error.exception.response, response)
        self.assertEqual(list(response.iter_content(chunk_size=5)), [b"first", b"second"])

    def test_wav_dimensions_samples_and_silence_use_an_independent_decoder(self):
        with wave.open(io.BytesIO(pcm_wav(4, 22050, 2, sample=1024, silence_frames=2))) as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (2, 22050, 6))
            self.assertEqual(struct.unpack("<12h", audio.readframes(6)), (1024,) * 8 + (0,) * 4)
