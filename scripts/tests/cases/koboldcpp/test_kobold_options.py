"""Kobold launcher option folding: the practice page implies the practice model."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import kobold


class KoboldOptionTests(unittest.TestCase):
    def _service(self, *argv: str):
        parser = kobold.build_parser()
        args = parser.parse_args(list(argv))
        # - apply_options folds flags into the shared service object, so it works on a copy
        with patch.object(cfg, "KOBOLDCPP_SERVICE", replace(cfg.KOBOLDCPP_SERVICE)):
            kobold.apply_options(args, parser)
            return cfg.KOBOLDCPP_SERVICE

    def _fold(self, *argv: str) -> str:
        return self._service(*argv).model

    def test_practice_page_selects_the_practice_model(self):
        self.assertEqual(self._fold("--practice-ui"), cfg.LANGUAGE_PRACTICE.llm_model)

    def test_practice_page_selects_the_practice_recognizer(self):
        self.assertIs(self._service("--practice-ui").transcription_engine, cfg.LANGUAGE_PRACTICE.asr_engine)

    def test_an_explicit_engine_wins_over_the_practice_default(self):
        chosen = next(engine for engine in cfg.AsrStartupEngine if engine is not cfg.LANGUAGE_PRACTICE.asr_engine)
        self.assertIs(
            self._service("--practice-ui", "--transcription-engine", chosen.value).transcription_engine, chosen
        )

    def test_a_plain_launch_keeps_transcription_off(self):
        self.assertIsNone(self._service().transcription_engine)

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
