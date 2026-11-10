"""Comment policy: markers, banner rules and commented-out code are rejected; prose is not."""

import tempfile
import unittest
from pathlib import Path

from scripts.review import comments


class CommentPolicyTests(unittest.TestCase):
    def _issues(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "module.py"
            path.write_text(body, encoding="utf-8")
            return comments.issues(path)

    def test_a_marker_comment_is_rejected(self):
        found = self._issues("# TODO: finish this\ndef value():\n    return 1\n")
        self.assertTrue(any("marker comment" in issue for issue in found))

    def test_a_reference_to_the_todo_document_is_not_a_marker(self):
        self.assertEqual(self._issues("# see notes/TODO.md for the failure\ndef value():\n    return 1\n"), [])

    def test_a_banner_rule_is_rejected(self):
        found = self._issues("# ======================\n\ndef value():\n    return 1\n")
        self.assertTrue(any("banner rule" in issue for issue in found))

    def test_commented_out_code_is_rejected(self):
        found = self._issues("# value = compute(2)\n\ndef value():\n    return 1\n")
        self.assertTrue(any("commented-out code" in issue for issue in found))

    def test_prose_that_explains_why_is_kept(self):
        body = "# - a frozen child holds the pipe open, so the stage ends here\ndef value():\n    return 1\n"
        self.assertEqual(self._issues(body), [])


if __name__ == "__main__":
    unittest.main()
