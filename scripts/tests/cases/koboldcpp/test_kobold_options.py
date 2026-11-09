"""Kobold launcher option folding: the practice page implies the practice model."""

import unittest

from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kobold


class KoboldOptionTests(unittest.TestCase):
    def _fold(self, *argv: str) -> str:
        parser = kobold.build_parser()
        args = parser.parse_args(list(argv))
        original = cfg.KOBOLDCPP_SERVICE.model
        try:
            kobold.apply_options(args, parser)
            return cfg.KOBOLDCPP_SERVICE.model
        finally:
            cfg.KOBOLDCPP_SERVICE.model = original

    def test_practice_page_selects_the_practice_model(self):
        self.assertEqual(self._fold("--practice-ui"), cfg.LANGUAGE_PRACTICE.llm_model)

    def test_an_explicit_model_wins_over_the_practice_default(self):
        chosen = next(label for label in cfg.KOBOLDCPP_MODELS if label != cfg.LANGUAGE_PRACTICE.llm_model)
        self.assertEqual(self._fold("--practice-ui", "--model", chosen), chosen)

    def test_a_plain_launch_keeps_the_character_model(self):
        self.assertEqual(self._fold(), cfg.KOBOLD_CHAT.llm_model)


if __name__ == "__main__":
    unittest.main()
