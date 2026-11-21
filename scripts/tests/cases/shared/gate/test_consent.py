"""A short run never asks; a run expected to pass five minutes asks, and refuses when nobody can answer."""

import argparse
import contextlib
import io
import sys
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

    def test_the_prompt_says_it_is_waiting_and_confirms_the_answer(self):
        printed = io.StringIO()
        with (
            patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: True, readline=lambda: "yes\n")),
            contextlib.redirect_stdout(printed),
        ):
            self.assertTrue(consent.ask("Framework update", 600))
        text = printed.getvalue()
        self.assertIn("Type yes to continue:", text)
        self.assertIn("[WAIT] nothing runs until you type yes", text)
        self.assertIn("[OK] confirmed", text)

    def test_the_boundary_is_five_minutes(self):
        self.assertFalse(consent.is_long(consent.LONG_RUN_SECONDS - 1))
        self.assertTrue(consent.is_long(consent.LONG_RUN_SECONDS))

    def test_the_flag_parses_and_defaults_to_asking(self):
        parser = argparse.ArgumentParser()
        consent.flag(parser)
        self.assertTrue(parser.parse_args(["--yes"]).yes)
        self.assertFalse(parser.parse_args([]).yes)

    def test_take_splits_the_flag_and_forward_puts_it_back(self):
        self.assertEqual(consent.take(["--yes", "--download"]), (True, ["--download"]))
        self.assertEqual(consent.take(["--download"]), (False, ["--download"]))
        self.assertEqual(consent.forward(True, ["--download"]), ["--yes", "--download"])
        self.assertEqual(consent.forward(False, ["--download"]), ["--download"])

    def test_confirm_asks_even_for_a_fast_irreversible_action(self):
        with (
            patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(consent.confirm("Stop every C:\\AI-owned service"))
        with patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)):
            self.assertTrue(consent.confirm("Stop every C:\\AI-owned service", given=True))

    def test_require_refuses_an_unattended_entry_point(self):
        with (
            patch("scripts.shared.consent.sys.stdin", Mock(isatty=lambda: False)),
            patch.object(sys, "argv", ["benchmark"]),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            consent.require(900)

    def test_require_accepts_yes_anywhere_and_keeps_help_free(self):
        with patch.object(sys, "argv", ["benchmark", "--yes", "--repeats", "1"]):
            consent.require(900)
            self.assertEqual(sys.argv[1:], ["--repeats", "1"])
        with patch.object(sys, "argv", ["benchmark", "--help"]), patch("scripts.shared.consent.sys.stdin") as stdin:
            consent.require(900)
        stdin.isatty.assert_not_called()
