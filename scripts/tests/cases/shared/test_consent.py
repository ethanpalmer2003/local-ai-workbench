"""A short run never asks; a run expected to pass five minutes asks, and refuses when nobody can answer."""

import argparse
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from scripts.shared import consent


class ConsentTests(unittest.TestCase):
    def test_a_short_run_never_asks(self):
        with patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)):
            self.assertTrue(consent.ask("Review gate", 55))

    def test_a_long_unattended_run_refuses_and_says_why(self):
        printed = io.StringIO()
        with patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)), contextlib.redirect_stdout(printed):
            self.assertFalse(consent.ask("Full validation", 600))
        self.assertIn("--yes", printed.getvalue())

    def test_yes_starts_a_long_run_without_a_terminal(self):
        with patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)):
            self.assertTrue(consent.ask("Full validation", 600, True))

    def test_the_person_at_the_terminal_answers(self):
        cases = (("yes\n", True), (" YES \n", True), ("no\n", False), ("", False))
        for answer, expected in cases:
            with (
                patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: True, readline=lambda: answer)),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(consent.ask("Full validation", 600), expected, answer)

    def test_the_boundary_is_five_minutes(self):
        self.assertFalse(consent.is_long(consent.LONG_RUN_SECONDS - 1))
        self.assertTrue(consent.is_long(consent.LONG_RUN_SECONDS))

    def test_the_flag_parses_and_defaults_to_asking(self):
        parser = argparse.ArgumentParser()
        consent.flag(parser)
        self.assertTrue(parser.parse_args(["--yes"]).yes)
        self.assertFalse(parser.parse_args([]).yes)
