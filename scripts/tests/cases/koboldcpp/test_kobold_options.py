"""Kobold launcher option folding: the practice page implies the practice model."""

import unittest
from dataclasses import replace
from unittest.mock import patch

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

    def test_image_flags_default_to_the_character_profile_and_no_image_clears_them(self):
        plain = kobold.build_parser().parse_args([])
        self.assertEqual(plain.with_image, cfg.KOBOLD_CHAT.image == "with")
        self.assertEqual(plain.image_on_demand, cfg.KOBOLD_CHAT.image == "on-demand")
        with patch.object(cfg, "KOBOLD_CHAT", replace(cfg.KOBOLD_CHAT, image="on-demand")):
            parser = kobold.build_parser()
            self.assertTrue(parser.parse_args([]).image_on_demand)
            disabled = parser.parse_args(["--no-image"])
            kobold.fold_image_flags(disabled)
        self.assertFalse(disabled.with_image)
        self.assertFalse(disabled.image_on_demand)


if __name__ == "__main__":
    unittest.main()
