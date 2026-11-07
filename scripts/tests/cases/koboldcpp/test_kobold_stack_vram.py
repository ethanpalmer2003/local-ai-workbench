"""Probe worker arguments and existing-service safety; no model launch."""

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.koboldcpp import kobold_stack_vram as probe
from scripts.launchers.koboldcpp import kobold
from scripts.launchers.runtime import shared_gpu
from scripts.launchers.sdcpp import server as sdcpp
from scripts.tests.shared.media_fixtures import PNG
from scripts.tests.shared.paths import CasePaths


class StackProbeTests(unittest.TestCase):
    def test_shared_kobold_offloads_layers_without_changing_standalone(self):
        shared = kobold.server_command("shared")
        self.assertEqual(shared[shared.index("--gpulayers") + 1], "16")
        self.assertEqual(shared[shared.index("--contextsize") + 1], "16384")
        self.assertEqual(shared[shared.index("--quantkv") + 1], "q8_0")
        self.assertNotIn("--gpulayers", kobold.server_command())
        self.assertNotIn("gpulayers", probe.cfg.KOBOLDCPP_KCPPS_ARGS)

    def test_text_workload_uses_chat_and_records_usage(self):
        text = "The teammate waited quietly beside the trees while we watched the distant facility. " * 2
        response = {"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 40}}
        with CasePaths(__file__).temporary_directory() as folder:
            paths = probe.RunPaths(Path(folder))
            paths.create()
            with patch.object(
                probe, "request", return_value=(200, json.dumps(response).encode(), "application/json")
            ) as request:
                self.assertEqual(probe.generate("text", paths, "test"), text.strip())
            self.assertTrue(request.call_args.args[0].endswith("/v1/chat/completions"))
            self.assertEqual(request.call_args.args[1]["max_tokens"], 128)
            result = json.loads((paths.artifacts / "test-text-result.json").read_text())
            self.assertEqual(result["response"]["usage"]["completion_tokens"], 40)

    def test_audio_and_image_kinds_report_no_reply_text(self):
        image = {"data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}
        with CasePaths(__file__).temporary_directory() as folder:
            paths = probe.RunPaths(Path(folder))
            paths.create()
            with patch.object(probe, "speech_request", return_value={"pcm": b"\x01\x00" * 1600}):
                self.assertIsNone(probe.generate("audio", paths, "audio"))
            with (
                patch.object(probe, "request", return_value=(200, json.dumps(image).encode(), "application/json")),
                patch.dict(probe.cfg.SDCPP_REQUEST_DEFAULTS, {"width": 1, "height": 1}),
            ):
                self.assertIsNone(probe.generate("image", paths, "image"))

    def test_shared_image_flags_do_not_affect_standalone(self):
        with patch.object(sdcpp, "launch_process") as launch:
            sdcpp.launch(extra_args=["--usage-profile", "shared"])
            shared = launch.call_args.args[0]
            self.assertIn("Vulkan0,te=cpu", shared)
            self.assertIn("512x512", shared)
            self.assertNotIn("--usage-profile", shared)
            sdcpp.launch()
            standalone = launch.call_args.args[0]
            self.assertNotIn("--vae-tiling", standalone)
            self.assertNotIn("Vulkan0,te=cpu", standalone)

    def test_audio_profile_preserves_native_source_and_unsupported_family(self):
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            source = root / "base.json"
            config = {
                "models": [
                    {"id": "breeze", "family": "breeze_tts", "path": "breeze.gguf"},
                    {
                        "id": "drama",
                        "family": "fish_drama3",
                        "path": "drama.gguf",
                        "session_options": {"fish_drama3.context_length": 2048},
                    },
                ]
            }
            source.write_text(json.dumps(config))
            with patch.object(shared_gpu.project_cfg, "GENERATED_DIR", root / "generated"):
                generated = shared_gpu.audio_config(source, 18888)
            effective = json.loads(generated.read_text())
            self.assertEqual(json.loads(source.read_text()), config)
            self.assertNotIn("session_options", effective["models"][0])
            self.assertEqual(
                effective["models"][1]["session_options"],
                {"fish_drama3.context_length": 2048, "fish_drama3.cpu_expert_layers": 40},
            )
            self.assertTrue(Path(effective["models"][0]["path"]).is_absolute())

    def test_worker_options_are_not_forwarded_to_backend(self):
        observed = []
        with (
            patch.object(sys, "argv", ["probe", "--worker", "audio"]),
            patch.object(probe.backends, "worker", side_effect=lambda name: observed.append((name, sys.argv.copy()))),
        ):
            probe.main()
        self.assertEqual(observed, [("audio", ["probe"])])

    def test_existing_service_is_refused(self):
        with (
            patch.object(probe.backends, "listening", return_value=True),
            self.assertRaisesRegex(RuntimeError, "existing services will not be replaced"),
        ):
            probe.backends.require_free("audio")


if __name__ == "__main__":
    unittest.main()
