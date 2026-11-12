"""Every label family uses only the values its owner declares, so a typo cannot pass as a label."""

import unittest

from scripts.benchmarks.shared.paths import Outcome
from scripts.config import models
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg
from scripts.tests.cases.asr.shared.coverage import coverage
from scripts.tests.shared.model_checks import requires_model_check
from scripts.tools import capability_matrix, probe_runner

BUDGET_CLASSES = {"smoke", "probe", "benchmark"}
SECTIONS = {"defaults", "alternatives"}
READINESS = {"resident-validated", "unreviewed", "disabled", "manual", "migrated-not-rerun"}
RUNNERS = {"resident_compare", "file_diagnostic", "whisper_embedded_compare", "gemma_audio_compare", "none"}
TIERS = {"transcription_ready", "broad_coverage", "adaptation_required"}


class LabelVocabularyTests(unittest.TestCase):
    def test_capability_rows_only_use_declared_budget_classes_and_sections(self):
        subjects = {subject for subject, _ in capability_matrix.CAPABILITIES}
        self.assertLessEqual(set(capability_matrix.CATEGORY.values()), BUDGET_CLASSES)
        self.assertLessEqual(set(capability_matrix.SECTION.values()), SECTIONS)
        self.assertEqual(set(capability_matrix.CATEGORY), subjects)
        self.assertEqual(set(capability_matrix.SECTION), subjects)
        self.assertFalse(set(capability_matrix.DEFERRED) - subjects)
        self.assertEqual(set(probe_runner.CATEGORY_SECONDS), BUDGET_CLASSES)

    def test_profiles_are_declared_and_their_defaults_name_a_catalog_model(self):
        stacks = (cfg.KOBOLD_CHAT, cfg.LANGUAGE_PRACTICE)
        for stack in stacks:
            self.assertIn(stack.profile, cfg.PROFILE_REQUIREMENTS)
        labels = {model.label for model in models.MODELS}
        self.assertEqual(set(cfg.TOOL_DEFAULTS), {"transcription", "embeddings"})
        self.assertEqual(set(cfg.MEDIA_DEFAULTS), {"image", "video"})
        for name, row in {**cfg.TOOL_DEFAULTS, **cfg.MEDIA_DEFAULTS}.items():
            with self.subTest(default=name):
                if row.model is not None:
                    self.assertIn(row.model, labels)
        # - Tool members live inside the tool profile; a media entry is its own profile.
        for name in cfg.MEDIA_DEFAULTS:
            self.assertIn(name, cfg.PROFILE_REQUIREMENTS)
        self.assertTrue(set(cfg.TOOL_DEFAULTS).isdisjoint(cfg.PROFILE_REQUIREMENTS))
        transcription, embeddings = (cfg.TOOL_DEFAULTS["transcription"].model, cfg.TOOL_DEFAULTS["embeddings"].model)
        assert transcription is not None and embeddings is not None
        self.assertEqual(models.path(transcription), cfg.QWEN3_ASR.model)
        self.assertEqual(models.path(embeddings), cfg.EMBEDDINGS_SERVER.model)
        self.assertIsNone(cfg.MEDIA_DEFAULTS["video"].model)
        self.assertIn("workflows/", cfg.MEDIA_DEFAULTS["video"].owner)
        self.assertEqual(cfg.ASR_SERVICE.engine, cfg.AsrStartupEngine.QWEN3_ASR)

    def test_profile_requirements_match_the_defaults_they_claim(self):
        agent_profiles = {name for name, row in cfg.PROFILE_REQUIREMENTS.items() if row.agent}
        self.assertEqual(agent_profiles, {"coding"})
        recognition = {name for name, row in cfg.PROFILE_REQUIREMENTS.items() if row.asr}
        self.assertEqual(recognition, {"language", "tool"})
        self.assertIsNotNone(cfg.LANGUAGE_PRACTICE.asr_engine)
        self.assertIn("transcription", cfg.TOOL_DEFAULTS)
        roles = {"mid", "lightweight", "coding", "none"}
        for name, row in cfg.PROFILE_REQUIREMENTS.items():
            with self.subTest(profile=name):
                self.assertIn(row.llm_role, roles)
        for stack in (cfg.KOBOLD_CHAT, cfg.LANGUAGE_PRACTICE):
            with self.subTest(stack=stack.profile):
                self.assertTrue(cfg.model_fits_profile(stack.profile, stack.tts_model))

    def test_tts_weights_declare_the_speech_class_the_profile_check_reads(self):
        from scripts.config.models import catalog

        weights = (".gguf", ".onnx", ".pth", ".safetensors")
        for model in models.models_for("tts"):
            with self.subTest(model=model.label):
                if model.filename is not None and model.filename.endswith(weights):
                    self.assertIn(model.speech_class, catalog.SPEECH_CLASSES)
                else:
                    self.assertIsNone(model.speech_class)
        self.assertEqual(cfg.tts_class_for("audiocpp/breeze-tts-2-q4_0"), cfg.TtsQualityClass.VOICE_DESIGN)
        self.assertEqual(cfg.tts_class_for("audiocpp/supertonic-3-q8_0"), cfg.TtsQualityClass.FAST_MULTILINGUAL)
        self.assertEqual(cfg.tts_class_for("tts/piper/lessac-medium/model"), cfg.TtsQualityClass.NONE)
        self.assertEqual(cfg.tts_class_for("unknown/model"), cfg.TtsQualityClass.NONE)

    def test_tts_weights_declare_the_voice_modes_they_accept(self):
        from scripts.config.models import catalog

        weights = (".gguf", ".onnx", ".pth", ".safetensors")
        for model in models.models_for("tts"):
            with self.subTest(model=model.label):
                if model.filename is not None and model.filename.endswith(weights):
                    self.assertTrue(model.speech_modes, model.label)
                    self.assertLessEqual(set(model.speech_modes), set(catalog.SPEECH_MODES))
                else:
                    self.assertEqual(model.speech_modes, ())
        self.assertEqual(set(models.get("audiocpp/breeze-tts-2-q4_0").speech_modes), {"clone", "design"})
        self.assertEqual(set(models.get("audiocpp/supertonic-3-q8_0").speech_modes), {"preset"})

    @requires_model_check
    def test_declared_modes_match_the_installed_audiocpp_specs(self):
        from scripts.launchers.audiocpp import audiocpp_catalog

        for model in models.models_for("tts"):
            if not model.label.startswith("audiocpp/") or model.path.suffix != ".gguf" or not model.path.is_file():
                continue
            spec = audiocpp_catalog.packaged_spec(model.path)
            if not spec.get("family"):
                continue
            with self.subTest(model=model.label):
                # - a spec with builtin voices is a preset model; one without takes a reference or instruction
                preset = bool(audiocpp_catalog.builtin_voices(model.path))
                self.assertEqual("preset" in model.speech_modes, preset)
                self.assertEqual("clone" in model.speech_modes, not preset)

    def test_delivery_and_speech_classes_keep_their_full_vocabulary(self):
        self.assertEqual(speech_delivery.MODES, ("streaming", "chunked", "whole"))
        self.assertLessEqual(set(speech_delivery.ASR_STREAMING), set(speech_delivery.ASR_CHUNKED))
        self.assertEqual({item.value for item in cfg.TtsQualityClass}, {"none", "fast-multilingual", "voice-design"})

    def test_run_outcomes_match_the_documented_set(self):
        self.assertEqual(
            {item.value for item in Outcome}, {"verified", "no-gain", "inconclusive", "superseded", "unreviewed"}
        )

    def test_asr_coverage_uses_declared_readiness_and_runner_values_and_covers_every_profile(self):
        rows = coverage()
        self.assertLessEqual({row["status"] for row in rows}, READINESS)
        self.assertLessEqual({row["runner"] for row in rows}, RUNNERS)
        self.assertEqual({row["engine"] for row in rows} - set(ASR_FILE_PROFILES) - _adapter_only(), set())
        self.assertEqual(set(ASR_FILE_PROFILES) - {row["engine"] for row in rows}, set())

    def test_language_tiers_only_use_declared_tiers(self):
        from scripts.config.models import model_languages

        catalog = model_languages.read_catalog()
        keys = {key for row in catalog["models"] for key in (row.get("coverage_tiers") or {})}
        self.assertLessEqual(keys, TIERS)


def _adapter_only() -> set[str]:
    """Resident adapters and manual tools that have no file profile of their own."""
    return {
        "handy",
        "koboldcpp-gemma-audio",
        "koboldcpp-whisper",
        "llamacpp-gemma-audio",
        "llamacpp-granite-5-2b",
        "llamacpp-qwen-1.7b",
        "parakeetcpp-cpu",
        "parakeetcpp-vulkan",
        "whispercpp-legacy-vulkan",
        "whispercpp-vulkan-fa",
    }


if __name__ == "__main__":
    unittest.main()
