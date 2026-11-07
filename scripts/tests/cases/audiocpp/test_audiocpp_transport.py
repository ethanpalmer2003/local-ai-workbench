"""Transport benchmark parsing and aggregation, without model inference."""

import base64
import json
import unittest

from scripts.tests.cases.audiocpp.audiocpp_transport import AudioReader, summary


class TransportBenchmark(unittest.TestCase):
    def test_network_fragments_produce_identical_pcm(self):
        pcm = b"\x00\x40\x00\xc0" * 12
        wire = (
            "data: "
            + json.dumps({"type": "speech.audio.delta", "audio": base64.b64encode(pcm).decode()})
            + "\r\n\r\ndata: [DONE]\r\n\r\n"
        ).encode()
        for transport, data in (("audio", pcm), ("sse", wire)):
            reader = AudioReader(transport, 24000)
            for byte in data:
                reader.feed(bytes([byte]))
            reader.finish()
            self.assertEqual(reader.pcm, pcm)

    def test_truncated_streams_fail(self):
        for reader in (
            AudioReader("audio", 24000, pcm=bytearray(b"x")),
            AudioReader("sse", 24000, pcm=bytearray(b"xx")),
        ):
            with self.assertRaises(RuntimeError):
                reader.finish()

    def test_summary_separates_transports(self):
        metrics = dict.fromkeys(
            ("first_audio_s", "elapsed_s", "rtf", "decode_cpu_ms", "body_to_pcm_ratio", "required_buffer_s"), 1.0
        )
        rows = summary([{**metrics, "transport": "sse"}, {**metrics, "transport": "audio", "elapsed_s": 2}])
        self.assertEqual(rows[0]["elapsed_s"], 1)
        self.assertEqual(rows[1]["elapsed_s"], 2)


if __name__ == "__main__":
    unittest.main()
