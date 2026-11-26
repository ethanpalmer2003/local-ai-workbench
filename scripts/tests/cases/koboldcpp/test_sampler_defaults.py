"""Server-side sampler defaults for the external llama.cpp arm, per model."""

import unittest
from unittest.mock import patch

from scripts.launchers import launcher_config as cfg
from scripts.launchers.koboldcpp import external_llm

ORION = "koboldcpp/TheDrummer_Orion-26B-A4B-v1.1-IQ3_XXS"


class SamplerDefaultTests(unittest.TestCase):
    def _command(self, model: str, defaults: dict[str, dict[str, float]]) -> list[str]:
        with patch.object(cfg, "MODEL_SAMPLER_DEFAULTS", defaults), patch.object(cfg, "KOBOLDCPP_SERVICE") as service:
            service.model = model
            return external_llm.command()

    def test_a_configured_model_emits_its_sampler_flags(self):
        command = self._command(ORION, {ORION: {"repeat_penalty": 1.18, "temperature": 0.9}})
        self.assertIn("--repeat-penalty", command)
        self.assertEqual(command[command.index("--repeat-penalty") + 1], "1.18")
        self.assertEqual(command[command.index("--temperature") + 1], "0.9")

    def test_a_model_without_defaults_adds_no_sampler_flags(self):
        command = self._command("koboldcpp/other", {})
        self.assertNotIn("--repeat-penalty", command)
        self.assertNotIn("--temperature", command)

    def test_an_unknown_sampler_key_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "Unknown sampler default"):
            self._command(ORION, {ORION: {"repeat_penality": 1.18}})

    def test_orion_keeps_the_tracked_repeat_penalty(self):
        # - the loop fix is a repository default; the overlay may add taste values such as temperature
        self.assertEqual(cfg.MODEL_SAMPLER_DEFAULTS[ORION]["repeat_penalty"], 1.18)

    def test_reasoning_stays_off_unless_the_kobold_config_asks_for_it(self):
        # - the no-model arm must not think more than a loaded one; the practice arm sends the same pair
        with patch.object(cfg, "KOBOLDCPP_KCPPS_ARGS", {**cfg.KOBOLDCPP_KCPPS_ARGS, "reasoningeffort": "none"}):
            self.assertEqual(
                external_llm.reasoning_defaults(),
                ["--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}'],
            )
        with patch.object(cfg, "KOBOLDCPP_KCPPS_ARGS", {**cfg.KOBOLDCPP_KCPPS_ARGS, "reasoningeffort": "medium"}):
            self.assertEqual(external_llm.reasoning_defaults(), [])


if __name__ == "__main__":
    unittest.main()
