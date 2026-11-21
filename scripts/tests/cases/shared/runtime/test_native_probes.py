"""Native probe commands carry the consent the stage already holds."""

import unittest

from scripts.tests.cases.suites import quick_validation


class ProbeCommandTests(unittest.TestCase):
    def test_a_long_probe_receives_yes_when_the_stage_was_told_yes(self):
        command = quick_validation.probe_command("gemma", True)
        self.assertIn("--yes", command)
        self.assertIn("scripts.benchmarks.asr.gemma_audio_compare", command)

    def test_a_short_probe_never_receives_the_flag_it_does_not_parse(self):
        self.assertNotIn("--yes", quick_validation.probe_command("parakeet", True))

    def test_without_consent_no_probe_is_handed_the_flag(self):
        self.assertNotIn("--yes", quick_validation.probe_command("gemma", False))


if __name__ == "__main__":
    unittest.main()
