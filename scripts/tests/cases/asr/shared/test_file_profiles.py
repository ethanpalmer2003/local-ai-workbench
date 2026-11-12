"""Model-free contracts for the additional ASR file adapters."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import models as model_cfg
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.launchers.asr.shared.file_cli import build_command, required_files
from scripts.tests.cases.asr.shared.metrics import pooled_scores, unicode_errors
from scripts.tests.shared.paths import CasePaths, RunPaths
from scripts.tests.shared.process_fixtures import running_process


class FileProfiles(unittest.TestCase):
    def test_latency_separates_clip_end_from_estimated_speech_end(self):
        from scripts.tests.cases.asr.shared.latency import latency_metrics

        result = latency_metrics({"audio_start": 0.1, "first_text": 1.1, "audio_end": 5.4, "final_text": 5.6}, 5.3, 4.8)
        self.assertAlmostEqual(result["first_text_seconds"], 1)
        self.assertAlmostEqual(result["final_after_audio_end_seconds"], 0.2)
        self.assertAlmostEqual(result["final_after_estimated_speech_end_seconds"], 0.7)
        self.assertAlmostEqual(result["pacing_elapsed_seconds"], 5.3)

    def test_ming_resident_path_normalizes_transcript_after_warmup(self):
        import time

        from scripts.benchmarks.asr.asr_resident_compare import run_engine
        from scripts.benchmarks.shared.resident_http import ResidentHttp

        with CasePaths(__file__).temporary_directory() as folder:
            run = RunPaths(Path(folder))
            run.create()
            model = run.temp / "fixture.gguf"
            model.write_bytes(b"fixture model")
            audio = run.temp / "fixture.wav"
            audio.write_bytes(b"fixture audio")
            clip = {"file": str(audio), "id": "clip", "language": "en", "duration_seconds": 1, "reference": "Hello"}
            with (
                patch.object(ResidentHttp, "start", lambda server: setattr(server, "process", running_process())),
                patch.object(ResidentHttp, "stop", lambda server: setattr(server, "process", None)),
                patch.object(ResidentHttp, "post", return_value={"text": "en\tHello"}) as post,
            ):
                result = run_engine(
                    "audiocpp-ming-audio-tiny",
                    ["fixture", "{config}"],
                    model,
                    [clip],
                    1,
                    run,
                    12345,
                    time.monotonic() + 10,
                )
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["samples"][0]["text"], "Hello")
            self.assertEqual(post.call_count, 2)

    def test_new_asr_profiles_keep_modes_models_and_generated_configs_distinct(self):
        from scripts.launchers.asr.shared.resident_profiles import audio_config, clean_transcript, profiles

        ming = audio_config("audiocpp-ming-audio-tiny")
        self.assertEqual(ming["models"][0]["family"], "ming3_audio")
        self.assertEqual(ming["models"][0]["task"], "asr")
        self.assertTrue(ming["models"][0]["session_options"]["ming3_audio.disk_experts"])
        self.assertEqual(audio_config("audiocpp-vulkan")["models"][0]["family"], "nemotron_asr")
        self.assertEqual(clean_transcript("audiocpp-ming-audio-tiny", "en\tHello there"), "Hello there")
        self.assertEqual(clean_transcript("audiocpp-vulkan", "en\tHello there"), "en\tHello there")
        audio = Path("sample.wav")
        qwen = audio_config("audiocpp-qwen3")
        self.assertEqual(qwen["models"][0]["family"], "qwen3_asr")
        self.assertTrue(qwen["models"][0]["session_options"]["packed_projections"])
        self.assertEqual(qwen["models"][0]["session_options"]["kv_cache_type"], "f16")
        self.assertIn("--session-option", build_command("audiocpp-qwen3", audio))
        self.assertIn("enable_thinking=false", build_command("audiocpp-ming-audio-tiny", audio))
        self.assertTrue(audio_config("audiocpp-ming-audio-tiny")["models"][0]["default_request_options"])
        command = build_command("parakeetcpp-nemotron-streaming", audio, "streaming")
        self.assertIn("--stream", command)
        self.assertNotIn("--vad", command)
        self.assertIn("cpu", Path(command[0]).parts)
        from scripts.launchers.asr.shared.file_cli import environment

        profile = ASR_FILE_PROFILES["parakeetcpp-nemotron-streaming"]
        self.assertEqual(environment(profile, "streaming")["PARAKEET_DEVICE"], "cpu")
        self.assertEqual(environment(profile, "offline")["PARAKEET_DEVICE"], "Vulkan0")
        self.assertIn("--vad", build_command("parakeetcpp-v3", audio))
        for key in ("parakeetcpp-v3", "audiocpp-ming-audio-tiny"):
            with self.assertRaises(ValueError):
                build_command(key, audio, "streaming")
        self.assertTrue(profiles(12345)["parakeetcpp-v3"][0][0].endswith("parakeet-server.exe"))

    def test_summary_pools_error_counts_instead_of_averaging_clip_rates(self):
        base = {
            "status": "completed",
            "engine": "demo",
            "mode": "offline",
            "seconds_including_startup": 1,
            "rtf_including_startup": 0.1,
            "reference_characters": 10,
            "cer": 0,
        }
        rows = [{**base, "reference_words": 10, "wer": 0.1}, {**base, "reference_words": 90, "wer": 0}]
        result = pooled_scores(rows)
        self.assertEqual(result["pooled_wer"], 0.01)
        self.assertEqual(result["samples"], 2)

    def test_commands_use_explicit_local_weights_and_same_audio(self):
        audio = Path("C:/AI/data/input/example.wav")
        for engine, profile in ASR_FILE_PROFILES.items():
            with self.subTest(engine=engine):
                command = build_command(engine, audio)
                self.assertEqual(command[0], str(profile.executable))
                self.assertIn(str(audio), command)
                self.assertTrue(all(path.is_absolute() for path in required_files(profile)))
                self.assertIn(str(model_cfg.path(profile.models[0])), " ".join(command))

    def test_modes_never_silently_fall_back(self):
        for engine in ("speechcpp",):
            with self.subTest(engine=engine), self.assertRaisesRegex(ValueError, "configured modes"):
                build_command(engine, Path("sample.wav"), "streaming")
        self.assertIn("--stream", build_command("nemo-speechcpp", Path("sample.wav"), "streaming"))
        self.assertIn("streaming", build_command("audiocpp-vulkan", Path("sample.wav"), "streaming"))

    def test_live_modes_use_local_vad_and_do_not_include_fake_file(self):
        command = build_command("speechcpp", None, "live")
        self.assertIn("--live", command)
        self.assertIn(str(model_cfg.path("asr/speechcpp/silero-vad")), command)
        self.assertNotIn("None", command)
        with self.assertRaisesRegex(ValueError, "input"):
            build_command("speechcpp", None)
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            build_command("speechcpp", Path("recording.wav"), "live")

    def test_unicode_scores_keep_non_latin_text_and_accents(self):
        self.assertEqual(unicode_errors("\u4f60\u597d", "\u4f60\u597d")["cer"], 0)
        self.assertEqual(unicode_errors("\u4f60\u597d", "\u4f60\u4eec")["cer"], 0.5)
        self.assertGreater(unicode_errors("caf\u00e9", "cafe")["cer"], 0)


if __name__ == "__main__":
    unittest.main()
