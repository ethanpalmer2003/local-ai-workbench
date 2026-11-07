"""Speech engine routing and CPU profile contracts without native model launches."""

import json
import unittest
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kobold, kobold_lite, kokoro
from scripts.tests.shared.paths import CasePaths


class KokoroProfiles(unittest.TestCase):
    def test_multilingual_default_retains_compact_package_option(self):
        self.assertEqual(cfg.KOKORO_TTS.audiocpp_package, "multilingual")
        self.assertEqual(cfg.KOKORO_TTS.audiocpp_model.name, "kokoro-82m-multilingual-q8_0.gguf")
        self.assertEqual(replace(cfg.KOKORO_TTS, audiocpp_package="small").audiocpp_model.name, "kokoro-82m-q8_0.gguf")
        self.assertEqual(kokoro.audio_environment()["AUDIOCPP_MECAB_LIBRARY"], str(cfg.KOKORO_TTS.mecab_library))

    def test_existing_session_is_not_replaced(self):
        with (
            patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.CONFIGURED),
            patch.object(kobold, "backend_running", return_value=True),
            patch.object(kobold, "start_kobold") as start,
            self.assertRaisesRegex(RuntimeError, "occupied"),
        ):
            kobold.main(["--speech-engine", "kokoro-internal"])
        start.assert_not_called()

    def test_internal_model_is_cpu_and_keeps_whisper(self):
        with patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", cfg.KoboldcppSpeechStartupEngine.KOKORO_INTERNAL):
            command = kobold.server_command("shared")
        self.assertEqual(command[command.index("--ttsmodel") + 1], str(cfg.KOKORO_TTS.koboldcpp_model))
        self.assertEqual(command[command.index("--ttsthreads") + 1], str(cfg.KOKORO_TTS.threads))
        self.assertIn("--whispermodel", command)
        self.assertNotIn("--ttsgpu", command)

    def test_external_config_selects_cpu_without_other_models(self):
        with (
            CasePaths(__file__).temporary_directory() as folder,
            patch.object(project_cfg, "GENERATED_DIR", Path(folder)),
        ):
            command = kokoro.audio_command(18881)
            config = json.loads(Path(command[command.index("--config") + 1]).read_text())
        self.assertEqual(config["backend"], "cpu")
        self.assertEqual(config["threads"], cfg.KOKORO_TTS.threads)
        self.assertEqual(
            [model["id"] for model in config["models"]], [cfg.KOKORO_TTS_PACKAGES[cfg.KOKORO_TTS.audiocpp_package]]
        )
        self.assertEqual(config["models"][0]["path"], str(cfg.KOKORO_TTS.audiocpp_model))
        self.assertEqual(command[-2:], ["--model", cfg.KOKORO_TTS_PACKAGES[cfg.KOKORO_TTS.audiocpp_package]])

    def test_speech_provider_routes_to_selected_engine(self):
        def serve(handler, *_args):
            instance = handler.__new__(handler)
            instance.path = "/v1/audio/speech"
            instance.headers = Message()
            instance._forward("POST")

        payload = json.dumps(
            {"input": "Hello", "model": "stale-model", "voice_ref": "stale.wav", "stream": True}
        ).encode()
        for engine in (
            cfg.KoboldcppSpeechStartupEngine.KOKORO_INTERNAL,
            cfg.KoboldcppSpeechStartupEngine.KOKORO_AUDIOCPP,
        ):
            with (
                self.subTest(engine=engine),
                patch.object(cfg.KOBOLDCPP_SERVICE, "speech_engine", engine),
                patch.object(kobold_lite, "serve_proxy", side_effect=serve),
                patch.object(kobold_lite, "read_request_body", return_value=payload),
                patch.object(kobold_lite, "relay_stream") as relay,
            ):
                kobold_lite.run_proxy()
                target = relay.call_args.args[2]
                body = json.loads(relay.call_args.args[4])
                port = cfg.KOBOLDCPP_KCPPS_ARGS["port"] if kokoro.internal() else cfg.AUDIOCPP_SERVICE.internal_port
                self.assertEqual(target, f"http://127.0.0.1:{port}/v1/audio/speech")
                self.assertEqual(body["voice"], cfg.KOKORO_TTS.voice)
                self.assertEqual(body["model"], cfg.KOKORO_TTS_PACKAGES[cfg.KOKORO_TTS.audiocpp_package])
                self.assertNotIn("voice_ref", body)
                if kokoro.internal():
                    self.assertFalse(body["stream"])
                    self.assertEqual(body["response_format"], "wav")
                else:
                    self.assertTrue(body["stream"])

    def test_invalid_speech_json_is_rejected_before_relay(self):
        with self.assertRaises(ValueError):
            kokoro.speech_body(b"[]")


if __name__ == "__main__":
    unittest.main()
