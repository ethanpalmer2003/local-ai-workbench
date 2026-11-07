"""Native and WebSocket ownership/framing contracts; no native libraries loaded."""

import ctypes
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.launchers.asr.parakeetcpp.streaming import Model, clean_transcript
from scripts.launchers.asr.shared.websocket_stream import WebSocketBridge
from scripts.launchers.shared.transport.http_input import chunks


class StreamingAdapters(unittest.TestCase):
    def test_parakeet_locale_marker_is_removed_only_at_the_end(self):
        self.assertEqual(clean_transcript("Bonjour. <fr-FR>"), "Bonjour.")
        self.assertEqual(clean_transcript("Say <en-US> inside a sentence."), "Say <en-US> inside a sentence.")

    def test_nemo_events_normalize_and_stream_ownership_is_bounded(self):
        bridge = WebSocketBridge("ws://127.0.0.1:9999/v1/audio/transcriptions/realtime", "fr", Path("unused.log"))
        stream = bridge.stream()
        stream.receive({"event": {"type": "session.updated"}})
        with patch.object(bridge, "send") as send:
            stream.start()
            self.assertEqual(send.call_args.args[0]["session"]["endpointing_ms"], 10000)
            stream.send(b"ab")
            stream.finish()
            self.assertEqual(send.call_args.args[0]["op"], "commit")
        stream.receive({"event": {"type": "conversation.item.input_audio_transcription.delta", "delta": "Bon"}})
        stream.receive({"event": {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Bonjour"}})
        self.assertEqual(stream.events.get_nowait()["delta"], "Bon")
        self.assertEqual(stream.events.get_nowait()["text"], "Bonjour")
        self.assertTrue(stream.done.is_set())
        other = bridge.stream()
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            bridge.stream()
        stream.close()
        other.close()
        self.assertEqual(bridge.streams, {})

    def test_parakeet_strings_and_sessions_are_freed_once(self):
        text = ctypes.create_string_buffer(b"hello")
        pointer = ctypes.addressof(text)
        functions = {key: Mock(return_value=None) for key in ("free", "free_stream", "free_string")}
        functions.update(load=Mock(return_value=1), last_error=Mock(return_value=b"failure"),
                         stream_begin_lang=Mock(return_value=2), stream_feed=Mock(return_value=pointer),
                         stream_finalize=Mock(return_value=pointer), stream_free=functions["free_stream"])
        library = Mock()
        library.bind.side_effect = lambda name, _args, _result: functions[name]
        with patch("scripts.launchers.asr.parakeetcpp.streaming.require_native_execution"), patch("scripts.launchers.asr.parakeetcpp.streaming.NativeLibrary", return_value=library):
            model = Model(Path("unused.dll"), Path("unused.gguf"))
            stream = model.stream("fr")
            self.assertEqual(stream.push(bytes(1024)), "hello")
            self.assertEqual(stream.finish(), "hello")
            stream.close()
            stream.close()
            model.close()
            model.close()
        self.assertEqual(functions["free_string"].call_count, 2)
        functions["free_stream"].assert_called_once_with(2)
        functions["free"].assert_called_once_with(1)

    def test_chunked_pcm_is_bounded_and_rejects_incomplete_samples(self):
        def handler(data):
            return SimpleNamespace(headers={"Transfer-Encoding": "chunked"}, rfile=io.BytesIO(data))
        self.assertEqual(list(chunks(handler(b"2\r\nab\r\n0\r\n\r\n"))), [b"ab"])
        for data in (b"1\r\na\r\n", b"2\r\na", b"-1\r\n", b"200000\r\n"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                list(chunks(handler(data)))


if __name__ == "__main__":
    unittest.main()
