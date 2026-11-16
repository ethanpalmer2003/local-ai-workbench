"""The declared-language matrix marks practice languages and states what it cannot claim."""

import unittest

from scripts.config.models import model_languages
from scripts.launchers import launcher_config as cfg
from scripts.tools import language_matrix


class LanguageMatrixTests(unittest.TestCase):
    def test_every_speech_checkpoint_gets_one_row(self):
        catalog = model_languages.read_catalog()
        rendered = language_matrix.rows(catalog)
        speech = [entry for entry in catalog["models"] if set(entry["tasks"]) & {"asr", "tts"}]
        self.assertEqual(len(rendered), len(speech))
        self.assertTrue(any(row["stage"] == "asr" for row in rendered))
        self.assertTrue(any(row["stage"] == "tts" for row in rendered))

    def test_practice_languages_are_marked_from_declared_codes(self):
        catalog = model_languages.read_catalog()
        rows = {row["name"]: row for row in language_matrix.rows(catalog)}
        supertonic = rows["Supertonic 3"]
        self.assertEqual(set(supertonic["cells"]), set(cfg.PRACTICE_LANGUAGES))
        self.assertTrue(all(supertonic["cells"][code] for code in cfg.PRACTICE_LANGUAGES))
        # - Parakeet v3 lists no Japanese, so the cell stays empty rather than guessed
        self.assertEqual(rows["Parakeet TDT 0.6B v3"]["cells"]["ja"], "")
        self.assertEqual(rows["Parakeet TDT 0.6B v3"]["cells"]["en"], "yes")

    def test_unknown_languages_stay_unknown_instead_of_blank(self):
        catalog = model_languages.read_catalog()
        rows = {row["name"]: row for row in language_matrix.rows(catalog)}
        gemma = rows["Gemma 4 E4B audio"]
        self.assertEqual(gemma["declared"], "unknown")
        self.assertFalse(any(gemma["cells"].values()))
        text = language_matrix.render(catalog)
        self.assertIn("Unknown: Gemma 4 E4B audio", text)
        self.assertIn("Declared support only", text)

    def test_the_page_matches_its_source(self):
        self.assertEqual(
            language_matrix.OUTPUT.read_text(encoding="utf-8"), language_matrix.render(model_languages.read_catalog())
        )


if __name__ == "__main__":
    unittest.main()
