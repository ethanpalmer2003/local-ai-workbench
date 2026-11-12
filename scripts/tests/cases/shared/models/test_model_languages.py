"""Speech-language counts, registry coverage and unknown-language semantics; no models loaded."""

import io
import json
import unittest
from contextlib import redirect_stdout

from scripts.config import models
from scripts.config.models import model_languages


class ModelLanguages(unittest.TestCase):
    def test_registered_speech_weights_have_coverage_or_explicit_unknown(self):
        catalog = model_languages.read_catalog()
        ids = [entry["distribution"] for entry in catalog["models"]]
        self.assertEqual(len(ids), len(set(ids)))
        covered = {key for entry in catalog["models"] for key in entry["model_ids"]}
        expected = {
            model.label
            for model in models.MODELS
            if model.group.startswith(("asr/", "audiocpp", "tts/"))
            and model.path.suffix in (".gguf", ".bin", ".pth", ".onnx")
            and not any(part in model.label for part in ("silero", "fsmn", "mmproj", "/voices"))
        }
        self.assertFalse(expected - covered, f"Missing language records: {expected - covered}")
        known = {model.label for model in models.MODELS}
        self.assertFalse(covered - known)
        for entry in catalog["models"]:
            self.assertTrue(entry["sources"])
            for field in ("languages", "locales"):
                codes = entry[field] or []
                self.assertEqual(len(codes), len(set(codes)))
                self.assertFalse({"auto", "multilingual"} & set(codes))

    def test_an_installed_spec_agrees_with_the_stored_locale_list(self):
        checked = []
        for entry in model_languages.read_catalog()["models"]:
            for model_id in entry["model_ids"]:
                declared = model_languages.packaged_locales(model_id) if "audiocpp" in model_id else None
                if declared and entry["locales"]:
                    checked.append(entry["name"])
                    self.assertEqual(set(entry["locales"]), set(declared), entry["name"])
        if not checked:
            self.skipTest("no AudioCpp weight with a packaged spec is installed")

    def test_locale_and_dialect_counts_are_not_inflated_language_counts(self):
        rows = {row["distribution"]: row for row in model_languages.select(model_languages.read_catalog())}
        nemo = rows["nemotron-3.5"]
        self.assertEqual((nemo["language_count"], nemo["locale_count"], nemo["ready_locale_count"]), (35, 40, 32))
        self.assertEqual(set(nemo["locales"]), {code for codes in nemo["coverage_tiers"].values() for code in codes})
        self.assertEqual((rows["kokoro-v1"]["language_count"], rows["kokoro-v1"]["locale_count"]), (8, 9))
        self.assertEqual((rows["qwen3-asr-0.6b"]["language_count"], rows["qwen3-asr-0.6b"]["dialect_count"]), (30, 22))
        self.assertIsNone(rows["gemma-e4b-audio"]["language_count"])

    def test_exact_model_identity_and_language_filters_preserve_unknowns(self):
        catalog = model_languages.read_catalog()
        self.assertEqual(
            model_languages.select(catalog, model="audiocpp/kokoro-kobold-q4")[0]["distribution"], "kokoro-v1"
        )
        french = model_languages.select(catalog, task="tts", language="French")
        ids = {row["distribution"] for row in french}
        self.assertIn("kokoro-v1", ids)
        self.assertNotIn("breeze-tts-2", ids)
        cantonese = {row["distribution"] for row in model_languages.select(catalog, language="yue")}
        self.assertIn("whisper-turbo", cantonese)
        self.assertNotIn("whisper-base", cantonese)
        self.assertNotIn("gemma-e4b-audio", cantonese)

    def test_cli_json_and_details_use_the_same_offline_catalog(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(model_languages.main(["--model", "breeze", "--json"]), 0)
        row = json.loads(output.getvalue())["models"][0]
        self.assertEqual(row["languages"], ["en", "zh"])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(model_languages.main(["--model", "nemotron", "--details"]), 0)
        self.assertIn("adaptation_required", output.getvalue())
        self.assertIn("fr-FR", output.getvalue())


if __name__ == "__main__":
    unittest.main()
