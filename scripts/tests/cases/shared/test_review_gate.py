"""Full review gate consent: an unattended run refuses, a person at the terminal answers the question."""

import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from scripts.review import __main__ as review


class ConsentTests(unittest.TestCase):
    def test_yes_flag_confirms_without_a_terminal(self):
        with patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: False)):
            self.assertTrue(review.consents(True))

    def test_unattended_run_is_refused_and_says_why(self):
        printed = io.StringIO()
        with (
            patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: False)),
            contextlib.redirect_stdout(printed),
        ):
            self.assertFalse(review.consents(False))
        self.assertIn("needs the user's agreement", printed.getvalue())

    def test_person_at_the_terminal_answers_the_question(self):
        cases = (("yes", True), (" YES ", True), ("no", False), ("", False))
        for answer, expected in cases:
            with (
                patch("scripts.review.__main__.sys.stdin", Mock(isatty=lambda: True)),
                patch("builtins.input", return_value=answer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(review.consents(False), expected, answer)


if __name__ == "__main__":
    unittest.main()
