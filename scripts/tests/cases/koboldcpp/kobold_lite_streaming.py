"""Contracts for modifying the installed Lite without replacing framework files."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp.kobold_lite import export_diff, patch_lite, preview_html, streaming_assets
from scripts.tests.shared.model_free import fixture_processes
from scripts.tests.shared.paths import CasePaths


class StreamingPatch(unittest.TestCase):
    def test_patch_adds_streaming_buffered_fallback_and_cancellation(self):
        original = '<body><script>function restart_new_game(save = true, keep_memory = false) { } function tts_speak_direct() {} function abort_generation() { }\n\t\t\t\tfetch(sub_endpt, {}); tts_speak_input_queue = text2.split("\\n").map(chunk => chunk.trim()).filter(chunk => chunk.length > 0);</script></body>'
        original = original.replace(
            "</script>",
            "let narrateonlydialog = localsettings.narrate_only_dialog; if(streamallowed && localsettings.tts_stream && !is_test) {} </script>",
        )
        patched = patch_lite(original)
        preset = cfg.AUDIOCPP_PROXY_MODEL_PRESETS[cfg.AudiocppModel.BREEZE_TTS]
        self.assertIn(f'"playback_buffer_ms": {preset.playback_buffer_ms}', patched)
        self.assertEqual(patched.count("window.koboldAudioStream.speak("), 1)
        self.assertIn("payload.stream = false", patched)
        self.assertIn("window.koboldAudioStream?.stop()", patched)
        self.assertIn("kobold_streaming.js", patched)
        self.assertIn("fetch(sub_endpt, {});", patched)
        self.assertIn("window.koboldAudioStream.chunkText(text)", patched)
        self.assertIn("toneInstruction(text)", patched)
        self.assertIn("payload._tone_tag = audioTone", patched)
        self.assertIn("useTextQueue(localsettings.tts_stream)", patched)

    @fixture_processes()
    def test_pr_preserves_native_text_controls_and_uses_identical_core(self):
        original = """<body><script>
        tts_stream: false,
        const selectedTTS = document.getElementById("ttsselect").value;
        document.getElementById("tts_stream").checked = localsettings.tts_stream;
        localsettings.tts_stream = (document.getElementById("tts_stream").checked?true:false);
        function abort_generation() {
        }
        function restart_new_game(save = true, keep_memory = false) {
        }
\t\t\t\tfetch(sub_endpt, {});
        </script><input title="Narration Streaming" type="checkbox" id="tts_stream">\n\t\t\t\t\t\t\t</div>\n\t\t\t\t\t\t</div></body>"""
        patched = patch_lite(original, "pr")
        self.assertIn("tts_stream_audio: false", patched)
        self.assertEqual(patched.count('id="tts_stream_audio"'), 1)
        self.assertNotIn("koboldAudioSettings", patched)
        self.assertNotIn("chunkText", patched)
        self.assertNotIn("kobold_streaming.js", patched)
        self.assertEqual(streaming_assets("local")[:2], streaming_assets("pr"))
        preview = preview_html(original, "pr")
        self.assertNotIn('src="pcm_audio.js"', preview)
        self.assertIn("display_settings_tab(3)", preview)
        self.assertIn("class Player", preview)
        diff = export_diff(original, "pr")
        core = streaming_assets("pr")[0].read_text(encoding="utf-8")
        self.assertIn("".join("+" + line for line in core.splitlines(True)), diff)
        with CasePaths(__file__).temporary_directory() as folder:
            root = Path(folder)
            (root / "index.html").write_text(original, encoding="utf-8", newline="\n")
            patch = root / "streaming.diff"
            patch.write_text(diff, encoding="utf-8", newline="\n")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True, timeout=10)
            subprocess.run(
                ["git", "apply", "--check", str(patch)], cwd=root, check=True, capture_output=True, timeout=10
            )
            subprocess.run(["git", "apply", str(patch)], cwd=root, check=True, capture_output=True, timeout=10)
            for asset in streaming_assets("pr"):
                self.assertEqual((root / asset.name).read_text(encoding="utf-8"), asset.read_text(encoding="utf-8"))

    @fixture_processes()
    def test_shared_player_and_browser_integrations(self):
        for name in ("pcm_audio.cjs", "kobold_streaming.cjs", "audiocpp_test_page.cjs", "audiocpp_comparison.cjs"):
            with self.subTest(name=name):
                owner = "koboldcpp" if name == "kobold_streaming.cjs" else "audiocpp"
                path = Path(__file__).parent.parent / owner / name
                result = subprocess.run([cfg.PI_CLIENT.node_cmd, str(path)], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_streaming_follows_the_shared_delivery_policy(self):
        from scripts.config.shared import speech_delivery
        from scripts.launchers.asr.shared import practice_models
        from scripts.launchers.koboldcpp import kobold_lite

        spec = {"id": cfg.LANGUAGE_PRACTICE.tts_model, "family": "kokoro_tts", "path": "unused", "mode": "streaming"}
        with (
            patch.object(practice_models, "active_tts_id", None),
            patch.object(practice_models, "tts_spec", return_value=spec),
            patch.object(speech_delivery, "overrides", return_value={}),
        ):
            self.assertEqual(kobold_lite.audio_delivery_plan()["mode"], "whole", "Lite-native TTS cannot stream")
            with patch.object(cfg.KOBOLDCPP_SERVICE, "transcription_engine", cfg.AsrStartupEngine.AUDIOCPP):
                self.assertEqual(kobold_lite.audio_delivery_plan()["mode"], "streaming")
                with patch.object(
                    speech_delivery, "overrides", return_value={f"tts:{practice_models.tts_id()}": "whole"}
                ):
                    self.assertEqual(kobold_lite.audio_delivery_plan()["mode"], "whole")
                with patch.object(kobold_lite.kokoro, "internal", return_value=True):
                    self.assertEqual(kobold_lite.audio_delivery_plan()["mode"], "whole")

    def test_incompatible_upstream_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_lite("<body>No supported TTS insertion point</body>")

    def test_external_llm_mode_seeds_the_provider_and_drops_the_local_model(self):
        from scripts.launchers.koboldcpp import external_llm, kobold, kobold_lite

        try:
            external_llm.server_exe()
        except FileNotFoundError:
            self.skipTest("llama.cpp is not installed in this checkout")
        command = external_llm.command()
        self.assertIn("--jinja", command)
        self.assertEqual(command[command.index("--alias") + 1], external_llm.ALIAS)
        self.assertNotIn("--nomodel", command)

        with patch.object(kobold.cfg.KOBOLDCPP_SERVICE, "streaming_ui", True):
            server = kobold.server_command("shared", no_model=True)
        self.assertIn("--nomodel", server)
        self.assertNotIn("--model", server)
        script = kobold_lite.external_script("http://127.0.0.1:9931/v1", "character-external")
        self.assertIn("kaihordewebui_custom_oai_endpoint", script)
        self.assertIn("http://127.0.0.1:9931/v1", script)
        self.assertIn("kaihordewebui_custom_oai_model", script)


if __name__ == "__main__":
    unittest.main()
