"""Manual full runs refuse: the gate and suite run at commit and push, not by hand."""

import runpy
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from scripts.shared import consent


class ManualRefusalTests(unittest.TestCase):
    def test_hook_stages_and_manual_pass_but_bare_runs_refuse(self):
        self.assertTrue(consent.manual_refused([]))
        self.assertTrue(consent.manual_refused(["--all"]))
        self.assertTrue(consent.manual_refused(["--fast"]))
        for argv in (["--commit"], ["--push"], ["--manual"], ["--all", "--manual"]):
            self.assertFalse(consent.manual_refused(argv), argv)

    def _entry_refuses(self, module: str) -> str:
        buffer = StringIO()
        with patch.object(sys, "argv", [module]), redirect_stdout(buffer), self.assertRaises(SystemExit) as outcome:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        self.assertEqual(outcome.exception.code, 2)
        return buffer.getvalue()

    def test_bare_gate_refuses_with_the_workflow_text(self):
        output = self._entry_refuses("scripts.review")
        self.assertIn("[REFUSE]", output)
        self.assertIn("--manual", output)

    def test_bare_suite_refuses_with_the_workflow_text(self):
        output = self._entry_refuses("scripts.tests.run")
        self.assertIn("[REFUSE]", output)
        self.assertIn("--manual", output)


if __name__ == "__main__":
    unittest.main()
