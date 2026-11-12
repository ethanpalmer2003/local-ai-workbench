"""American spelling policy: British variants are reported with the American form."""

import unittest

from scripts.review import spellings


class AmericanSpellingTests(unittest.TestCase):
    def test_a_british_variant_is_reported_with_its_american_form(self):
        self.assertEqual(
            spellings.scan_text("doc.md", "The quantisation and behaviour of the catalogue.\n"),
            [(1, "quantisation", "quantization"), (1, "behaviour", "behavior"), (1, "catalogue", "catalog")],
        )
        self.assertEqual(spellings.scan_text("doc.md", "Two quantisations.\n"), [(1, "quantisations", "quantizations")])

    def test_case_is_preserved(self):
        for british, expected in (("Summarise", "Summarize"), ("CANCELLED", "CANCELED"), ("practise", "practice")):
            with self.subTest(british=british):
                match = spellings.PATTERN.match(british)
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(spellings.american(match), expected)

    def test_a_word_inside_another_is_not_a_variant(self):
        self.assertEqual(
            spellings.scan_text("doc.md", "A practised ear hears the grey area.\n"),
            [(1, "practised", "practiced"), (1, "grey", "gray")],
        )


if __name__ == "__main__":
    unittest.main()
