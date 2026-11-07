"""Model-free turn ownership, pre-roll, VAD option scope and duplex HTTP contracts."""

import queue
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.launchers.asr.shared.vad import command, parse_event
from scripts.launchers.audiocpp.asr_turns import Turns
from scripts.launchers.shared.transport.streaming_http import StreamingPost
from scripts.tests.shared.http_server import server


class VadTurns(unittest.TestCase):
    def test_streaming_settings_use_session_scope(self):
        cmd = command()
        self.assertNotIn("--request-option", cmd)
        self.assertIn("threshold=0.5", cmd)
        self.assertIn("min_silence_duration_ms=700", cmd)
        self.assertEqual(cmd[cmd.index("--backend") + 1], "cpu")
        event = parse_event("event=speech_end sample=16000 probability=0.02")
        assert event is not None
        self.assertEqual(event["sample"], 16000)
        self.assertIsNone(parse_event("family=silero_vad"))

    def test_preroll_is_forwarded_once_and_silence_finishes_one_turn(self):
        turns = Turns("http://127.0.0.1:12345", Path("unused.log"))
        stream = SimpleNamespace(
            events=queue.Queue(), done=threading.Event(), start=Mock(), send=Mock(), finish=Mock(), close=Mock()
        )
        turns.samples, turns.history = 20000, bytearray(b"ab" * 20000)
        with patch("scripts.launchers.asr.shared.turns.StreamingPost", return_value=stream):
            turns.vad.events.put({"type": "speech_start", "sample": 16000})
            turns.poll()
            assert turns.active is not None
            self.assertEqual(turns.active["start_sample"], 11200)
            self.assertEqual(len(stream.send.call_args.args[0]), 17600)
            turns.vad.events.put({"type": "speech_end", "sample": 18000})
            turns.poll()
            stream.finish.assert_called_once()
            stream.events.put({"type": "transcript.text.done", "text": "hello"})
            result = turns.poll()
        self.assertEqual(result[0]["end_reason"], "silence")
        self.assertEqual(turns.pending, [])
        self.assertIsNone(turns.active)
        stream.close.assert_called_once()

    def test_silence_opens_no_asr_and_partial_frames_are_rejected(self):
        turns = Turns("http://127.0.0.1:12345", Path("unused.log"))
        with patch("scripts.launchers.asr.shared.turns.StreamingPost") as create:
            self.assertEqual(turns.poll(), [])
            with self.assertRaises(ValueError):
                turns.push(b"odd")
            create.assert_not_called()

    def test_lost_preroll_is_reported_instead_of_clipping_speech(self):
        turns = Turns("http://127.0.0.1:12345", Path("unused.log"))
        turns.samples, turns.history = 40000, bytearray(1024)
        turns.vad.events.put({"type": "speech_start", "sample": 16000})
        with self.assertRaisesRegex(RuntimeError, "pre-roll"):
            turns.poll()

    def test_duplex_upload_survives_connection_close_response_header(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                pass

            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                size = int(self.rfile.readline(), 16)
                self.rfile.read(size + 2)
                self.wfile.write(b'data: {"type":"partial","text":"hello"}\n\n')
                self.wfile.flush()
                if self.rfile.readline() == b"0\r\n":
                    self.rfile.readline()
                    self.wfile.write(b'data: {"type":"final","text":"hello"}\n\n')
                    self.wfile.flush()

        with server(Handler) as url:
            post = StreamingPost(url)
            try:
                post.start()
                post.send(b"pcm")
                self.assertEqual(post.events.get(timeout=3)["type"], "partial")
                post.finish()
                self.assertEqual(post.events.get(timeout=3)["type"], "final")
            finally:
                post.close()
