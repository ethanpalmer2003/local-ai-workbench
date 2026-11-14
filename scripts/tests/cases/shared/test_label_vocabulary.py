"""Every label family uses only the values its owner declares, so a typo cannot pass as a label."""

import unittest

from scripts.benchmarks.asr.coverage import coverage
from scripts.benchmarks.shared.paths import Outcome
from scripts.config import models
from scripts.config.asr.file_profiles import ASR_FILE_PROFILES
from scripts.config.models import catalog
from scripts.config.shared import deferred as parked
from scripts.config.shared import speech_delivery
from scripts.launchers import launcher_config as cfg
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
        self.assertFalse({entry.subject for entry in parked.records() if entry.subject} - subjects)
        self.assertEqual(set(probe_runner.CATEGORY_SECONDS), BUDGET_CLASSES)

    def test_profiles_are_declared_by_the_stacks_that_run_them(self):
        for stack in (cfg.KOBOLD_CHAT, cfg.LANGUAGE_PRACTICE):
            with self.subTest(stack=stack.profile):
                self.assertIn(stack.profile, cfg.PROFILE_REQUIREMENTS)
        self.assertEqual(cfg.ASR_SERVICE.engine, cfg.AsrStartupEngine.QWEN3_ASR)

    def test_profile_requirements_match_the_defaults_they_claim(self):
        agent_profiles = {name for name, row in cfg.PROFILE_REQUIREMENTS.items() if row.agent}
        self.assertEqual(agent_profiles, {"coding"})
        recognition = {name for name, row in cfg.PROFILE_REQUIREMENTS.items() if row.asr}
        self.assertEqual(recognition, {"language", "tool"})
        self.assertIsNotNone(cfg.LANGUAGE_PRACTICE.asr_engine)
        for stack in (cfg.KOBOLD_CHAT, cfg.LANGUAGE_PRACTICE):
            with self.subTest(stack=stack.profile):
                self.assertTrue(cfg.model_fits_profile(stack.profile, stack.tts_model))

    def test_tts_weights_declare_the_speech_class_the_profile_check_reads(self):
        weights = (".gguf", ".onnx", ".pth", ".safetensors")
        for model in models.models_for("tts"):
            with self.subTest(model=model.label):
                if model.filename is not None and model.filename.endswith(weights):
                    self.assertIn(model.speech_class, catalog.SPEECH_CLASSES)
                else:
                    self.assertIsNone(model.speech_class)
        self.assertEqual(cfg.tts_class_for("audiocpp/breeze-tts-2-q4_0"), catalog.SpeechClass.VOICE_DESIGN)
        self.assertEqual(cfg.tts_class_for("audiocpp/supertonic-3-q8_0"), catalog.SpeechClass.FAST_MULTILINGUAL)
        self.assertEqual(cfg.tts_class_for("tts/piper/lessac-medium/model"), catalog.SpeechClass.NONE)
        self.assertEqual(cfg.tts_class_for("unknown/model"), catalog.SpeechClass.NONE)

    @requires_model_check
    def test_voice_modes_stay_with_the_model_metadata(self):
        from scripts.launchers.audiocpp import audiocpp_catalog

        for model in models.models_for("tts"):
            self.assertFalse(hasattr(model, "speech_modes"), model.label)
            if not model.label.startswith("audiocpp/") or model.path.suffix != ".gguf" or not model.path.is_file():
                continue
            # - the framework's own spec is the authority the UI reads for preset vs clone
            self.assertIsInstance(audiocpp_catalog.packaged_spec(model.path), dict)

    def test_catalog_roles_mark_what_their_consumer_reads(self):
        # - only "chat" drives behavior today: the practice page's chat picker
        chat = [row for row in models.MODELS if "chat" in row.roles]
        self.assertTrue(chat)
        for row in chat:
            with self.subTest(model=row.label):
                self.assertTrue(row.filename and row.filename.endswith(".gguf"), row.label)
                self.assertNotIn("projector", row.roles)
        self.assertFalse(
            [row.label for row in models.MODELS if "projector" in row.roles and "mmproj" not in (row.filename or "")]
        )
        self.assertEqual(
            {row.label for row in models.MODELS if "embedding" in row.roles}, {"embeddings/embeddinggemma-2-Q8_0"}
        )
        self.assertEqual(
            {row.label for row in models.MODELS if "coding" in row.roles},
            {"llamacpp/Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp"},
        )

    def test_delivery_and_speech_classes_keep_their_full_vocabulary(self):
        self.assertEqual(speech_delivery.MODES, ("streaming", "chunked", "whole"))
        self.assertLessEqual(set(speech_delivery.ASR_STREAMING), set(speech_delivery.ASR_CHUNKED))
        self.assertEqual({item.value for item in catalog.SpeechClass}, {"none", "fast-multilingual", "voice-design"})

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

    def test_parked_work_declares_a_kind_and_names_real_rows(self):
        entries = parked.records()
        self.assertTrue(entries)
        self.assertLessEqual({entry.kind.value for entry in entries}, {item.value for item in parked.DeferredKind})
        subjects = {subject for subject, _ in capability_matrix.CAPABILITIES}
        named = {entry.subject for entry in entries if entry.subject}
        self.assertLessEqual(named, subjects)
        self.assertEqual({entry.subject for entry in entries if entry.reason}, named)


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
