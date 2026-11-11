"""Low integrity label check and repair; the ACL calls are mocked, nothing is changed."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.config import project_config as project_cfg
from scripts.tools import low_integrity


def icacls_output(text: str):
    from subprocess import CompletedProcess

    return CompletedProcess(["icacls"], 0, stdout=text, stderr="")


class LowIntegrityTests(unittest.TestCase):
    def test_a_low_label_line_is_detected(self):
        output = icacls_output("path Mandatory Label\\Low Mandatory Level:(OI)(CI)(NW)\n")
        with patch.object(low_integrity.subprocess, "run", return_value=output):
            self.assertTrue(low_integrity.is_low(low_integrity.label(Path("path"))))

    def test_medium_is_not_reported_as_low(self):
        output = icacls_output("path Mandatory Label\\Medium Mandatory Level:(NW)\n")
        with patch.object(low_integrity.subprocess, "run", return_value=output):
            self.assertFalse(low_integrity.is_low(low_integrity.label(Path("path"))))

    def test_fix_sets_medium_on_the_root_and_existing_subtrees(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bat").mkdir()
            with patch.object(project_cfg, "BASE_DIR", root), patch.object(low_integrity.subprocess, "run") as run:
                self.assertEqual(low_integrity.fix(), 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("(OI)(CI)Medium" in " ".join(command) for command in commands))
        self.assertTrue(any("/T" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
