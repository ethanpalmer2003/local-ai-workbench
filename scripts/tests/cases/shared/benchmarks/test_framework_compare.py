"""Language comparison request shaping, corpus hand-off and report math; no server is started."""

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.benchmarks.shared import framework_compare as compare


class FakeResponse:
    def __init__(self, lines: list[bytes] | None = None, content: bytes = b"", payload: object = None) -> None:
        self.lines = lines or []
        self.content = content
        self.text = ""
        self.status_code = 200
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exception: object) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self) -> list[bytes]:
        return self.lines

    def json(self) -> object:
        return self._payload


def served(backend: str = "practice") -> compare.Served:
    return compare.Served(
        backend=backend,
        chat="http://chat",
        tts="http://speech",
        asr="http://asr",
        chat_model="gemma",
        tts_model="kokoro",
        asr_model="nemotron",
    )


class StreamChatTests(unittest.TestCase):
    def test_delta_parsing_skips_keepalives_and_the_terminator(self):
        self.assertIsNone(compare._delta_text(b""))
        self.assertIsNone(compare._delta_text(b"data: [DONE]"))
        self.assertIsNone(compare._delta_text(b"data: not-json"))
        self.assertIsNone(compare._delta_text(b'data: {"choices":[{"delta":{}}]}'))
        self.assertEqual(compare._delta_text(b'data: {"choices":[{"delta":{"content":"hi"}}]}'), "hi")

    def test_a_server_error_frame_is_reported_instead_of_counting_as_content(self):
        line = b'data: {"error":{"code":"model_not_found","message":"Model \'kokoro\' was not found"}}'
        self.assertIsNone(compare._delta_text(line))
        reported = compare._error_text(line)
        self.assertIsNotNone(reported)
        self.assertIn("kokoro", reported or "")

    def test_a_stream_that_only_reports_an_error_fails_loudly(self):
        lines = [b'data: {"error":{"message":"model still loading"}}', b"data: [DONE]"]
        with (
            patch.object(compare.requests, "post", return_value=FakeResponse(lines)),
            self.assertRaises(RuntimeError) as raised,
        ):
            compare.stream_chat(served(), "hello", 8)
        self.assertIn("model still loading", str(raised.exception))

    def test_thinking_deltas_are_counted_apart_from_spoken_content(self):
        lines = [
            b'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}',
            b'data: {"choices":[{"delta":{"reasoning_content":"more"}}]}',
            b"data: [DONE]",
        ]
        with patch.object(compare.requests, "post", return_value=FakeResponse(lines)):
            row = compare.stream_chat(served(), "hello", 8)
        self.assertEqual((row["chunks"], row["reasoning_chunks"]), (0, 2))
        self.assertIsNone(row["first_token_seconds"])

    def test_stream_chat_counts_content_chunks_after_the_role_delta(self):
        lines = [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            b'data: {"choices":[{"delta":{"content":"a"}}]}',
            b'data: {"choices":[{"delta":{"content":"b"}}]}',
            b"data: [DONE]",
        ]
        with patch.object(compare.requests, "post", return_value=FakeResponse(lines)) as post:
            row = compare.stream_chat(served(), "hello", 8)
        self.assertEqual(row["chunks"], 2)
        self.assertIsNotNone(row["first_token_seconds"])
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8)
        self.assertEqual(post.call_args.args[0], "http://chat/v1/chat/completions")


class SpeechLegTests(unittest.TestCase):
    def test_speech_sends_the_language_option_and_records_audio_seconds(self):
        response = FakeResponse(content=b"RIFF....")
        with tempfile.TemporaryDirectory() as folder:
            run = MagicMock(artifacts=Path(folder))
            with (
                patch.object(compare.requests, "post", return_value=response) as post,
                patch.object(compare, "decode_audio", return_value=([0.0] * 24000, 24000)),
            ):
                row = compare._tts_row(served(), run, ("ja", "ja", "jf_alpha", "こんにちは"))
            self.assertEqual((Path(folder) / "practice-ja.wav").read_bytes(), b"RIFF....")
        self.assertEqual(row["status"], "measured")
        self.assertAlmostEqual(row["audio_seconds"], 1.0)
        self.assertEqual(post.call_args.kwargs["json"]["options"], {"language": "ja"})
        self.assertEqual(post.call_args.args[0], "http://speech/v1/audio/speech")

    def test_a_rejected_sentence_marks_the_row_unavailable_instead_of_raising(self):
        with patch.object(compare.requests, "post", side_effect=compare.requests.RequestException("404 no kokoro")):
            row = compare._tts_row(served(), MagicMock(artifacts=Path("artifacts")), ("fr", "fr-fr", "ff_siwis", "x"))
        self.assertEqual(row["status"], "unavailable")
        self.assertIn("404 no kokoro", row["reason"])

    def test_a_leg_with_no_measured_sentence_keeps_the_first_reason(self):
        with (
            patch.object(compare, "_speech", return_value=(b"RIFF....", 0.1)),
            patch.object(compare, "_tts_row", return_value={"status": "unavailable", "reason": "no backend"}),
        ):
            leg = compare._tts_leg(served(), MagicMock())
        self.assertEqual(leg["status"], "unavailable")
        self.assertEqual(leg["reason"], "no backend")

    def test_a_speaker_that_cannot_warm_up_skips_the_leg_with_its_reason(self):
        with patch.object(compare, "_speech", side_effect=compare.requests.RequestException("no kokoro")):
            leg = compare._tts_leg(served(), MagicMock())
        self.assertEqual(leg["status"], "unavailable")
        self.assertIn("no kokoro", leg["reason"])


class RecognitionLegTests(unittest.TestCase):
    def test_transcription_scores_word_and_character_errors_against_the_reference(self):
        clip = {"id": "en-0", "language": "en", "file": __file__, "reference": "one two three", "duration_seconds": 2.0}
        response = FakeResponse(payload={"text": "one four three"})
        with patch.object(compare.requests, "post", return_value=response) as post:
            row = compare._asr_row(served(), clip)
        self.assertEqual(row["status"], "measured")
        self.assertAlmostEqual(row["wer"], 1 / 3)
        self.assertEqual(row["reference_words"], 3)
        self.assertIn("multipart/form-data", post.call_args.kwargs["headers"]["Content-Type"])

    def test_pooled_scores_group_clips_by_language(self):
        rows = [
            {"language": "en", "wer": 0.5, "cer": 0.1, "reference_words": 10, "reference_characters": 20},
            {"language": "en", "wer": 0.0, "cer": 0.0, "reference_words": 10, "reference_characters": 20},
            {"language": "ja", "wer": 1.0, "cer": 0.5, "reference_words": 4, "reference_characters": 10},
        ]
        pooled = compare._pooled(rows)
        self.assertEqual([row["language"] for row in pooled], ["en", "ja"])
        self.assertAlmostEqual(pooled[0]["pooled_cer"], 0.05)
        self.assertAlmostEqual(pooled[1]["pooled_cer"], 0.5)


class SummaryTests(unittest.TestCase):
    def test_summary_means_chat_requests_and_marks_unmeasured_backends(self):
        results = [
            {
                "backend": "lemonade",
                "startup_seconds": 1.0,
                "models": {"chat": "m.gguf", "tts": "kokoro-v1", "asr": "Whisper-Tiny"},
                "legs": {
                    "chat": {
                        "status": "measured",
                        "model": "m.gguf",
                        "requests": [
                            {"chunks": 8, "first_token_seconds": 0.5, "chunks_per_second": 4.0},
                            {"chunks": 6, "first_token_seconds": 0.7, "chunks_per_second": 3.0},
                        ],
                    },
                    "tts": {"status": "unavailable", "reason": "no kokoro", "rows": []},
                    "asr": {
                        "status": "measured",
                        "languages": [{"language": "en", "samples": 5, "pooled_wer": 0.1, "pooled_cer": 0.02}],
                    },
                },
            },
            {
                "backend": "practice",
                "startup_seconds": 2.0,
                "models": {"chat": "m.gguf", "tts": "kokoro", "asr": "nemotron"},
                "legs": {"chat": {"status": "unavailable", "reason": "no health", "requests": []}},
            },
        ]
        text = compare.summarize(results)
        self.assertIn("| lemonade | m.gguf | 1.0 | 0.60 | 3.50 |", text)
        self.assertIn("| practice | m.gguf | n/a | n/a | n/a |", text)
        self.assertIn("| lemonade | kokoro-v1 | unavailable | - | - | - |", text)
        self.assertIn("| lemonade | Whisper-Tiny | en | 5 | 10.0% | 2.0% |", text)
        self.assertIn("- lemonade tts: no kokoro", text)
        self.assertIn("- practice chat: no health", text)

    def test_a_thinking_backend_is_marked_rather_than_shown_as_zero_speed(self):
        results = [
            {
                "backend": "lemonade",
                "startup_seconds": 2.0,
                "models": {"chat": "m.gguf", "tts": "kokoro-v1", "asr": "Whisper-Tiny"},
                "legs": {
                    "chat": {
                        "status": "measured",
                        "model": "m.gguf",
                        "requests": [{"chunks": 0, "reasoning_chunks": 12, "first_token_seconds": None}],
                    }
                },
            }
        ]
        self.assertIn("| lemonade | m.gguf | 2.0 | thinking only | thinking only |", compare.summarize(results))

    def test_speech_that_differs_in_length_between_stacks_is_named(self):
        results = [
            {
                "backend": "practice",
                "models": {"chat": "m.gguf", "tts": "kokoro", "asr": "nemotron"},
                "legs": {
                    "tts": {
                        "status": "measured",
                        "rows": [
                            {
                                "language": "fr",
                                "status": "measured",
                                "audio_seconds": 4.1,
                                "voice": "ff_siwis",
                                "real_time_factor": 0.1,
                            }
                        ],
                    }
                },
            },
            {
                "backend": "lemonade",
                "models": {"chat": "m.gguf", "tts": "kokoro-v1", "asr": "Whisper-Tiny"},
                "legs": {
                    "tts": {
                        "status": "measured",
                        "rows": [
                            {
                                "language": "fr",
                                "status": "measured",
                                "audio_seconds": 0.5,
                                "voice": "ff_siwis",
                                "real_time_factor": 0.6,
                            }
                        ],
                    }
                },
            },
        ]
        self.assertIn("speech fr: the stacks produced different amounts of audio", compare.summarize(results))

    def test_status_needs_at_least_one_measurement_per_selected_leg_set(self):
        options = compare.Options(legs=("chat", "tts", "asr"), tokens=8, requests_count=1, clips=1)
        nothing = [{"backend": "practice", "legs": {"chat": {"status": "unavailable"}}}]
        self.assertEqual(compare._status(nothing, options), "failed")
        measured = [{"backend": "practice", "legs": {"chat": {"status": "measured"}}}]
        self.assertEqual(compare._status(measured, options), "passed")


class WhisperArmTests(unittest.TestCase):
    @contextmanager
    def stub(self, backend):
        yield served(backend)

    def test_the_whisper_arm_measures_recognition_only(self):
        options = compare.Options(legs=("chat", "tts", "asr"), tokens=8, requests_count=1, clips=1)
        asr = {"status": "measured", "rows": [], "languages": []}
        with (
            patch.object(compare, "serve", return_value=self.stub("whisper")),
            patch.object(compare, "_asr_leg", return_value=asr),
            patch.object(compare, "_chat_leg") as chat,
            patch.object(compare, "_tts_leg") as tts,
        ):
            result = compare.measure("whisper", Path("m.gguf"), MagicMock(), options, [])
        self.assertEqual(set(result["legs"]), {"asr"})
        chat.assert_not_called()
        tts.assert_not_called()

    def test_the_whisper_arm_names_its_own_weights(self):
        self.assertEqual(
            compare._recogniser_model(compare.WHISPER_ENGINE, []), Path(str(compare.cfg.WHISPERCPP_ASR.model)).stem
        )
        self.assertEqual(compare._recogniser_path(compare.WHISPER_ENGINE), Path(compare.cfg.WHISPERCPP_ASR.model))

    def test_a_recognition_only_arm_is_absent_from_the_chat_and_speech_tables(self):
        results = [{"backend": "whisper", "models": {"chat": "-", "tts": "-", "asr": "whisper"}, "legs": {}}]
        text = compare.summarize(results)
        self.assertNotIn("| whisper |", text)


class LemonadeModelTests(unittest.TestCase):
    def test_the_chat_model_is_the_listed_id_not_the_folder(self):
        catalog = {
            "gemma-4-E4B-it-Q4_0": {"path": "C:/models/gemma-4-E4B-it-Q4_0.gguf"},
            "multilingual_models": {"path": "C:/models"},
        }
        chosen = compare._lemonade_chat_model(catalog, Path("C:/models/gemma-4-E4B-it-Q4_0.gguf"))
        self.assertEqual(chosen, "gemma-4-E4B-it-Q4_0")

    def test_missing_weights_report_the_ids_lemonade_offers(self):
        with self.assertRaises(RuntimeError) as raised:
            compare._lemonade_chat_model({"other": {}}, Path("C:/models/missing.gguf"))
        self.assertIn("missing.gguf", str(raised.exception))
        self.assertIn("other", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
