"""Accuracy metric contracts used by the saved-audio Whisper comparison."""

import unittest

from scripts.benchmarks.asr.shared.metrics import word_errors
from scripts.benchmarks.asr.whisper_embedded_compare import command


class WhisperCompareTests(unittest.TestCase):
    def test_only_explicit_flash_variant_enables_flash(self):
        self.assertNotIn("-ng", command("latest-vulkan"))
        self.assertIn("-nfa", command("latest-vulkan"))
        self.assertIn("-fa", command("vulkan-fa"))
        self.assertNotIn("-nfa", command("vulkan-fa"))

    def test_formatting_and_equivalent_spelling_are_not_recognition_errors(self):
        result = word_errors("Let's practice at a caf\u00e9.", "LET'S practice at a cafe!")
        self.assertEqual(result, {"word_errors": 0, "reference_words": 5, "wer": 0.0})

    def test_insertions_deletions_and_substitutions_are_counted(self):
        self.assertEqual(word_errors("one two three", "one four three five")["word_errors"], 2)
        self.assertEqual(word_errors("one two three", "one three")["word_errors"], 1)
        self.assertAlmostEqual(word_errors("one two three", "one four three five")["wer"], 2 / 3)

    def test_missing_reference_does_not_claim_zero_error(self):
        self.assertIsNone(word_errors("", "one")["wer"])


if __name__ == "__main__":
    unittest.main()
